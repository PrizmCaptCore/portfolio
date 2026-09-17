"""
Inference RunPod Serverless handler (chat completions).

Hosts Gemma 4 E2B-it via vLLM for real-time meeting summary / intent.
Embeddings are served from a separate endpoint (`runpod_embedding/`) on
scale-to-zero — kept apart so this endpoint can stay always-on without
paying GPU for the sparse embedding workload.

RunPod endpoint:
  POST /runsync   {"input": {"messages": [...], "_internal_key": "<key>", ...}}

Input mirrors OpenAI chat completions body — pass it directly. `model` is
optional; when omitted the handler falls back to MODEL_TAG.

Set env vars on the RunPod template:
  RELAY_INTERNAL_KEY
  RELAY_INTERNAL_KEY_PREV  (optional)
  SUMMARY_MODEL            (optional — default matches the baked-in repo)
  VLLM_MAX_MODEL_LEN       (optional — default 8192)
  VLLM_MAX_NUM_SEQS        (optional — default 16)
  VLLM_GPU_MEM_UTIL        (optional — default 0.85)
"""

import os
import subprocess
import time

import httpx
import runpod

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

print("Inference (chat) ready")


# ── handler ───────────────────────────────────────────────────────────────────

def handler(job: dict) -> dict:
    """
    job["input"] accepts the full OpenAI chat completions body, e.g.:
       {"messages": [...], "model": "...", "temperature": 0.7, ...}

    `_internal_key` is stripped before forwarding.
    """
    job_input = job.get("input", {})

    key = job_input.get("_internal_key", "")
    if not _valid_key(key):
        return {"error": "unauthorized"}

    body = {k: v for k, v in job_input.items() if k != "_internal_key"}
    # Always override `model` — caller's value (e.g. legacy "gemma4:e2b") is
    # ignored so backing model identifier stays internal.
    body["model"] = MODEL_TAG

    try:
        resp = httpx.post(
            f"http://localhost:{VLLM_PORT}/v1/chat/completions",
            json=body,
            timeout=300.0,
        )
        resp.raise_for_status()
        result = resp.json()
        # Mask backing model on response with a generic service label.
        if isinstance(result, dict) and "model" in result:
            result["model"] = "relay-chat"
        return result
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
