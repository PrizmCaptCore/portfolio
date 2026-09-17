"""
Embedding server — RunPod Pod deployment (Qwen3-Embedding-0.6B via vLLM).

Runs scale-to-zero on RunPod Serverless (Min Workers: 0) for sparse batch
workloads — Notion sync, periodic reindex, etc.

Endpoints:
  GET  /health           — requires X-Internal-Key header
  POST /v1/embeddings    — OpenAI-compatible, requires X-Internal-Key header

Wire format (OpenAI-compatible):
  request:  {"input": "text" | ["text1", "text2"], "model": "..." (optional)}
  response: {"data": [{"embedding": [...], "index": 0}, ...], "model": ..., "usage": ...}

Set env vars on RunPod Pod:
  RELAY_INTERNAL_KEY
  RELAY_INTERNAL_KEY_PREV  (optional)
  MODEL_NAME               (optional — default matches the baked-in repo)
  VLLM_MAX_MODEL_LEN       (optional — default 8192)
  VLLM_MAX_NUM_SEQS        (optional — default 32)
  VLLM_GPU_MEM_UTIL        (optional — default 0.85)
"""

import asyncio
import os
import signal
import subprocess
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
        if _vllm_running():
            ready = True
            break
        time.sleep(2)

    if not ready:
        raise RuntimeError(f"vLLM did not become ready on port {VLLM_PORT} within 15min")

print("Embedder ready")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Embedding Server (RunPod)")


@app.middleware("http")
async def check_internal_key(request: Request, call_next):
    key = request.headers.get("X-Internal-Key", "")
    if not _valid_key(key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


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


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    body = await request.json()
    # Always override `model` — caller's value is ignored so backing model
    # identifier stays internal.
    body["model"] = MODEL_TAG
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"http://localhost:{VLLM_PORT}/v1/embeddings",
            json=body,
        )
    payload = resp.json()
    if isinstance(payload, dict) and "model" in payload:
        payload["model"] = "relay-embedding"
    return JSONResponse(content=payload, status_code=resp.status_code)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
