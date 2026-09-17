"""
EN→KO Translation server — RunPod Pod deployment (TranslateGemma 4B via vLLM).

Endpoints (identical to the previous Ollama-backed Pod):
  GET  /health        — requires X-Internal-Key header
  POST /translate     — {"text": "..."} → {"translation": "..."}

Set env vars on RunPod Pod:
  RELAY_INTERNAL_KEY
  RELAY_INTERNAL_KEY_PREV  (optional)
  HF_TOKEN                 (required — gated TranslateGemma weights)
  MODEL_NAME               (optional override of the HF repo)
  VLLM_MAX_MODEL_LEN       (optional — default 4096)
  VLLM_MAX_NUM_SEQS        (optional — default 16, raise for more concurrency)
  VLLM_GPU_MEM_UTIL        (optional — default 0.85)
"""

import asyncio
import os
import re
import signal
import subprocess
import time

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
    if key == internal_key:
        return True
    if internal_key_prev and key == internal_key_prev:
        return True
    return False


def _clean(t: str) -> str:
    t = re.sub(r"\*+", "", t).strip()
    t = TRAILING_META_RE.sub("", t).strip()
    return t


# ── startup ───────────────────────────────────────────────────────────────────

def _vllm_running() -> bool:
    try:
        return httpx.get(
            f"http://localhost:{VLLM_PORT}/v1/models", timeout=2.0
        ).status_code == 200
    except Exception:
        return False


# vLLM is a separate subprocess; when /admin/reload SIGTERMs us, the
# subprocess survives the FastAPI restart. Detecting that on the next
# boot lets us skip the model reload — only the FastAPI layer bounces.
if _vllm_running():
    print(f"vLLM already running on :{VLLM_PORT}, reusing")
else:
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

    # First boot may take several minutes for HF download + weight load.
    deadline = time.time() + 900
    ready = False
    while time.time() < deadline:
        if _vllm_running():
            ready = True
            break
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


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Translation Server (RunPod)")


@app.middleware("http")
async def check_internal_key(request: Request, call_next):
    key = request.headers.get("X-Internal-Key", "")
    if not _valid_key(key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


class Req(BaseModel):
    text: str


class Res(BaseModel):
    translation: str


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_TAG}


@app.post("/admin/reload")
async def admin_reload():
    """Exit so entrypoint.sh re-pulls and restarts. vLLM survives the
    bounce (separate subprocess + _vllm_running() check on next boot)
    so reload is just a FastAPI restart (~1-2s), not a model reload.
    Auth is handled by the global X-Internal-Key middleware."""
    loop = asyncio.get_running_loop()
    loop.call_later(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"status": "reloading"}


def _is_translate_model() -> bool:
    return "translate" in MODEL_TAG.lower()


async def _call(client: httpx.AsyncClient, text: str, extra: str = "") -> str:
    """
    TranslateGemma's chat template requires a multimodal-style content list
    with custom keys (source_lang_code/target_lang_code). vLLM's OpenAI
    server normalizes `messages` and strips those keys, so we apply the
    chat template locally with the model's tokenizer and send the raw
    prompt to /v1/completions instead of /v1/chat/completions.

    Async (with caller-supplied httpx.AsyncClient) so concurrent
    /translate requests don't serialize on the event loop — under the
    old sync httpx.post, N concurrent requests fanned out into bimodal
    latencies (one lane per uvicorn worker) instead of running in
    parallel through vLLM's continuous batcher.
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
        resp = await client.post(VLLM_COMPLETIONS_URL, json=body, timeout=300.0)
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
    resp = await client.post(VLLM_CHAT_URL, json=body, timeout=300.0)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


@app.post("/translate", response_model=Res)
async def translate(req: Req):
    text = req.text.strip()
    if not text:
        return Res(translation="")
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            out = _clean(await _call(client, text))
            if CHINESE_RE.search(out):
                out = _clean(await _call(
                    client, text,
                    extra="Output MUST be Korean (한국어) only. No Chinese characters allowed.",
                ))
        return Res(translation=out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
