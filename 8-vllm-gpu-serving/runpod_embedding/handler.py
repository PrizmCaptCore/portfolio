"""
Embedding RunPod Serverless handler (Qwen3-Embedding-0.6B via vLLM).

Runs scale-to-zero (Min Workers: 0) for sparse batch workloads — Notion
sync, periodic reindex, etc. Idle cost ~$0; cold start ~30s-1min thanks
to baked-in weights.

RunPod endpoint:
  POST /runsync  {"input": {"input": ["text1", "text2"], "_internal_key": "<key>"}}

Input mirrors OpenAI embeddings body — pass it directly. `model` is
optional; when omitted the handler falls back to MODEL_TAG.

Set env vars on the RunPod template:
  RELAY_INTERNAL_KEY
  RELAY_INTERNAL_KEY_PREV  (optional)
  MODEL_NAME               (optional — default matches the baked-in repo)
  VLLM_MAX_MODEL_LEN       (optional — default 8192)
  VLLM_MAX_NUM_SEQS        (optional — default 32)
  VLLM_GPU_MEM_UTIL        (optional — default 0.85)
"""

import os
import subprocess
import time

import httpx
import runpod

MODEL_TAG = os.environ.get("MODEL_NAME", "Qwen/Qwen3-Embedding-0.6B")
VLLM_PORT = 8001

MAX_MODEL_LEN = int(os.environ.get("VLLM_MAX_MODEL_LEN", "8192"))
MAX_NUM_SEQS = int(os.environ.get("VLLM_MAX_NUM_SEQS", "32"))
GPU_MEM_UTIL = float(os.environ.get("VLLM_GPU_MEM_UTIL", "0.85"))

internal_key = os.environ.get("RELAY_INTERNAL_KEY", "")
internal_key_prev = os.environ.get("RELAY_INTERNAL_KEY_PREV", "")


def _valid_key(key: str) -> bool:
    if not internal_key:
        return False
    return key == internal_key or (internal_key_prev and key == internal_key_prev)


# ── startup ───────────────────────────────────────────────────────────────────

print(f"Starting vLLM (embed) with {MODEL_TAG} …")
# Modern vLLM (0.10+) auto-detects embedding architecture from the
# model's HF config — `--task embed` was removed.
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

print("Embedder ready")


# ── handler ───────────────────────────────────────────────────────────────────

def handler(job: dict) -> dict:
    """
    job["input"] forwards directly to OpenAI-compatible /v1/embeddings:
       {"input": "text" | ["text1", "text2"], "model": "..." (optional)}

    `_internal_key` is stripped before forwarding.
    """
    job_input = job.get("input", {})

    key = job_input.get("_internal_key", "")
    if not _valid_key(key):
        return {"error": "unauthorized"}

    body = {k: v for k, v in job_input.items() if k != "_internal_key"}
    # Always override `model` — caller's value is ignored so backing model
    # identifier stays internal.
    body["model"] = MODEL_TAG

    try:
        resp = httpx.post(
            f"http://localhost:{VLLM_PORT}/v1/embeddings",
            json=body,
            timeout=300.0,
        )
        resp.raise_for_status()
        result = resp.json()
        # Mask backing model on response with a generic service label.
        if isinstance(result, dict) and "model" in result:
            result["model"] = "relay-embedding"
        return result
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
