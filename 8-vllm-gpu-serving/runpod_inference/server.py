"""
Inference server — RunPod Pod deployment (chat completions).

Hosts Gemma 4 E2B-it via vLLM for real-time meeting summary / intent.
Embeddings are served from a separate endpoint (`runpod_embedding/`) on
scale-to-zero, since they're a sparse batch workload.

Public endpoints (X-Internal-Key required on all):
  GET  /health                — backend ready check
  POST /v1/chat/completions   — OpenAI-compatible

Set env vars on RunPod Pod:
  RELAY_INTERNAL_KEY
  RELAY_INTERNAL_KEY_PREV  (optional)
  SUMMARY_MODEL            (optional — default matches the baked-in repo)
  VLLM_MAX_MODEL_LEN       (optional — default 8192)
  VLLM_MAX_NUM_SEQS        (optional — default 16)
  VLLM_GPU_MEM_UTIL        (optional — default 0.85)
"""

import asyncio
import json
import os
import signal
import subprocess
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODEL_TAG = os.environ.get("SUMMARY_MODEL", "google/gemma-4-E2B-it")
VLLM_PORT = 8001

MAX_MODEL_LEN = int(os.environ.get("VLLM_MAX_MODEL_LEN", "8192"))
MAX_NUM_SEQS = int(os.environ.get("VLLM_MAX_NUM_SEQS", "16"))
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
# boot lets us skip the ~60s model reload — only the FastAPI layer
# bounces.
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

    deadline = time.time() + 900
    ready = False
    while time.time() < deadline:
        if _vllm_running():
            ready = True
            break
        time.sleep(2)

    if not ready:
        raise RuntimeError(f"vLLM did not become ready on port {VLLM_PORT} within 15min")

print("Inference (chat) ready")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Inference Server (RunPod)")


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
    so a reload is just a FastAPI restart (~1-2s), not a model reload.
    Auth is handled by the global X-Internal-Key middleware."""
    loop = asyncio.get_running_loop()
    loop.call_later(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"status": "reloading"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    # Always override `model` — caller's value is ignored so backing model
    # identifier stays internal.
    body["model"] = MODEL_TAG
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"http://localhost:{VLLM_PORT}/v1/chat/completions",
            json=body,
        )
    payload = resp.json()
    if isinstance(payload, dict) and "model" in payload:
        payload["model"] = "relay-chat"
    return JSONResponse(content=payload, status_code=resp.status_code)


@app.post("/v1/chat/stream")
async def chat_stream(request: Request):
    """Streaming variant of chat completions — SSE forward from vLLM.

    Forces `stream: true` regardless of what the caller passed, so this
    endpoint always returns an SSE stream. Pairs with the existing
    non-streaming /v1/chat/completions, which summary / batch paths
    keep using unchanged.

    Like the non-streaming endpoint, each SSE chunk's `model` field is
    rewritten to "relay-chat" so the backing model identity stays
    internal. Per-chunk JSON parse adds ~20µs each — over a typical
    7s generation that's ~5-10ms total, well below the noise floor.
    """
    body = await request.json()
    body["model"] = MODEL_TAG
    body["stream"] = True

    async def event_source():
        # AsyncClient must span the full generator lifetime — the SSE
        # connection has to stay open while we forward chunks. Opening
        # it in the handler body and letting it close before yielding
        # would cut the stream off immediately.
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"http://localhost:{VLLM_PORT}/v1/chat/completions",
                json=body,
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        # aiter_lines emits empty strings for the SSE
                        # `\n\n` event separators; we re-emit our own
                        # terminators below so swallow these.
                        continue
                    if line.startswith("data: "):
                        payload_str = line[6:]
                        if payload_str == "[DONE]":
                            yield b"data: [DONE]\n\n"
                            continue
                        try:
                            payload = json.loads(payload_str)
                            if isinstance(payload, dict) and "model" in payload:
                                payload["model"] = "relay-chat"
                            yield (
                                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                            ).encode()
                        except json.JSONDecodeError:
                            # Malformed payload — forward as-is rather
                            # than dropping it. Surfaces upstream bugs
                            # without breaking the stream.
                            yield (line + "\n\n").encode()
                    else:
                        # Non-data SSE lines (event:, id:, retry:, …)
                        # forwarded verbatim. vLLM doesn't emit these
                        # today but the protocol allows them.
                        yield (line + "\n").encode()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
