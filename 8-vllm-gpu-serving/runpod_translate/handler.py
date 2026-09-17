"""
EN→KO Translation RunPod Serverless handler (TranslateGemma 4B via vLLM).

RunPod endpoint:
  POST /runsync  {"input": {"text": "Hello world", "_internal_key": "<key>"}}
  →              {"output": {"translation": "안녕 세상"}}

Set env vars on the RunPod template:
  RELAY_INTERNAL_KEY
  RELAY_INTERNAL_KEY_PREV  (optional, for rolling key updates)
  MODEL_NAME               (optional — default matches the baked-in repo)
  VLLM_MAX_MODEL_LEN       (optional — default 4096)
  VLLM_MAX_NUM_SEQS        (optional — default 16)
  VLLM_GPU_MEM_UTIL        (optional — default 0.85)
"""

import os
import re
import subprocess
import time

import httpx
import runpod
from transformers import AutoTokenizer

MODEL_TAG = os.environ.get("MODEL_NAME", "google/translategemma-4b-it")
VLLM_PORT = 8001

MAX_MODEL_LEN = int(os.environ.get("VLLM_MAX_MODEL_LEN", "4096"))
MAX_NUM_SEQS = int(os.environ.get("VLLM_MAX_NUM_SEQS", "16"))
GPU_MEM_UTIL = float(os.environ.get("VLLM_GPU_MEM_UTIL", "0.85"))

internal_key = os.environ.get("RELAY_INTERNAL_KEY", "")
internal_key_prev = os.environ.get("RELAY_INTERNAL_KEY_PREV", "")

SYSTEM_PROMPT = (
    "You are a Korean translator. Translate the English text into Korean.\n\n"
    "RULES (strictly follow all):\n"
    "- Output EXACTLY ONE Korean translation — a single sentence or phrase\n"
    "- NO alternatives, NO options, NO \"또는\", NO \"혹은\" between variants\n"
    "- NO explanations, NO notes, NO asterisks (*), NO bullet points\n"
    "- NO meta-commentary\n"
    "- Output ONLY the Korean translation text and nothing else\n"
    "- Preserve proper nouns and technical terms as-is\n"
    "- Use natural conversational Korean (구어체)\n"
    "- Omit filler words"
)

CHINESE_RE = re.compile(r"[一-鿿㐀-䶿]")
TRAILING_META_RE = re.compile(r"\s*어떤 번역이[^。.]*[。.]?\s*$")


def _valid_key(key: str) -> bool:
    if not internal_key:
        return False
    return key == internal_key or (internal_key_prev and key == internal_key_prev)


def _clean(t: str) -> str:
    t = re.sub(r"\*+", "", t).strip()
    t = TRAILING_META_RE.sub("", t).strip()
    return t


# ── startup ───────────────────────────────────────────────────────────────────

print(f"Starting vLLM with {MODEL_TAG} …")
# Prefix caching is on by default in modern vLLM (0.10+); the explicit
# `--enable-prefix-caching` flag was deprecated/removed in some versions.
subprocess.Popen([
    "python3", "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL_TAG,
    "--port", str(VLLM_PORT),
    "--max-model-len", str(MAX_MODEL_LEN),
    "--max-num-seqs", str(MAX_NUM_SEQS),
    "--gpu-memory-utilization", str(GPU_MEM_UTIL),
])

deadline = time.time() + 900
ready = False
while time.time() < deadline:
    try:
        if httpx.get(f"http://localhost:{VLLM_PORT}/v1/models", timeout=2.0).status_code == 200:
            ready = True
            break
    except Exception:
        pass
    time.sleep(2)

if not ready:
    raise RuntimeError(f"vLLM did not become ready on port {VLLM_PORT} within 15min")

VLLM_CHAT_URL = f"http://localhost:{VLLM_PORT}/v1/chat/completions"
VLLM_COMPLETIONS_URL = f"http://localhost:{VLLM_PORT}/v1/completions"

# Load the model's tokenizer locally so we can apply its jinja chat template
# directly. vLLM's OpenAI server normalizes `messages` into its own
# multimodal format and strips custom keys like `source_lang_code` —
# applying the template ourselves and sending the raw prompt to
# /v1/completions bypasses that normalize step.
_tokenizer = AutoTokenizer.from_pretrained(MODEL_TAG)
print("Translator ready")


# ── translation helpers ───────────────────────────────────────────────────────

def _is_translate_model() -> bool:
    return "translate" in MODEL_TAG.lower()


def _call(text: str, extra: str = "") -> str:
    """
    TranslateGemma's chat template requires a multimodal-style content list
    with custom keys (source_lang_code/target_lang_code). vLLM's OpenAI
    server normalizes `messages` and strips those keys, so we apply the
    chat template locally with the model's tokenizer and send the raw
    prompt to /v1/completions instead of /v1/chat/completions.
    """
    if _is_translate_model():
        messages = [{
            "role": "user",
            "content": [{
                "type": "text",
                "source_lang_code": "en",
                "target_lang_code": "ko",
                "text": text,
            }],
        }]
        prompt = _tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        body = {
            "model": MODEL_TAG,
            "prompt": prompt,
            "temperature": 0.1,
            "max_tokens": 512,
        }
        resp = httpx.post(VLLM_COMPLETIONS_URL, json=body, timeout=300.0)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["text"].strip()

    # Generic chat fallback (used if MODEL_NAME is swapped to a non-translate
    # model). Standard OpenAI message format works fine here.
    system = SYSTEM_PROMPT + (f"\n\nREMINDER: {extra}" if extra else "")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]
    body = {
        "model": MODEL_TAG,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 512,
    }
    resp = httpx.post(VLLM_CHAT_URL, json=body, timeout=300.0)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ── handler ───────────────────────────────────────────────────────────────────

def handler(job: dict) -> dict:
    """
    Input:  {"text": "Hello world", "_internal_key": "<key>"}
    Output: {"translation": "안녕 세상"}
    """
    job_input = job.get("input", {})

    key = job_input.get("_internal_key", "")
    if not _valid_key(key):
        return {"error": "unauthorized"}

    text = job_input.get("text", "").strip()
    if not text:
        return {"translation": ""}

    try:
        out = _clean(_call(text))
        if CHINESE_RE.search(out):
            out = _clean(_call(
                text,
                extra="Output MUST be Korean (한국어) only. No Chinese characters allowed.",
            ))
        return {"translation": out}
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
