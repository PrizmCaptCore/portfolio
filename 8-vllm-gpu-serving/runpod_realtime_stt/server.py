"""
RealtimeSTT streaming STT server — RunPod Pod deployment.

Public protocol (identical to runpod_stt/server.py so the Tauri client's
nemo_provider.rs needs no changes):
  Client → Server : binary frames  — raw f32 LE PCM, 16 kHz mono
  Server → Client : JSON text frame — {"text": "...", "is_partial": bool}
  Client → Server : JSON {"cmd": "reset"}

Auth: ?key=<HMAC-token-or-static-internal-key>
  RELAY_INTERNAL_KEY      current static key (also verifies HMAC tokens)
  RELAY_INTERNAL_KEY_PREV previous static key (rolling-update grace period)

Internally this is a thin adapter:
  client WS (port 8765)  →  this process  →  vLLM Realtime WS (localhost:8001)

vLLM Realtime API (OpenAI-compatible) is the actual transcription engine.
The adapter converts audio (f32 → base64 PCM16) and translates events
(transcription.delta / transcription.done → our partial/final shape).
Each client WS opens a 1:1 upstream WS so vLLM's continuous batcher
treats sessions as independent requests.

RunPod Pod: expose port 8765, access via
  wss://<pod-id>-8765.proxy.runpod.net/?key=<token>
"""

import argparse
import asyncio
import base64
import gc
import hashlib
import hmac as hmac_mod
import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time

# bitsandbytes is required when vLLM is started with
# `--quantization bitsandbytes` (below). It's not in the base image
# because we only need it for INT4 quantization mode; entrypoint.sh
# is baked into the image and can't be amended via the zero-rebuild
# git-pull path, so the install lives here in server.py instead. The
# import check makes this a no-op on subsequent boots — pip is only
# called on the very first launch of a fresh Pod. Promote into the
# Dockerfile pip install once we commit to INT4 as the permanent
# quantization path (faster cold start, offline-friendly).
try:
    import bitsandbytes  # noqa: F401
except ImportError:
    print("[server] installing bitsandbytes (one-time per pod)…", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "bitsandbytes>=0.46"]
    )

import httpx
import numpy as np
import uvicorn
import websockets
from fastapi import FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

SAMPLE_RATE = 16_000
IDLE_TIMEOUT_SEC = 120

MODEL_TAG = os.environ.get(
    "MODEL_NAME", "<realtime-stt-model-hf-id>"
)
VLLM_PORT = 8001
VLLM_HOST = "localhost"
VLLM_REALTIME_URL = f"ws://{VLLM_HOST}:{VLLM_PORT}/v1/realtime"

# vLLM v0.21.0's RealtimeConnection (entrypoints/openai/realtime/) ONLY
# accepts {type, model} in session.update — modalities, input_audio_format,
# transcription_delay_ms, language, temperature etc. that the OpenAI
# Realtime standard documents are NOT validated and silently dropped.
# RealtimeSTT's commit-delay knob is therefore not configurable through this
# protocol; whatever the model's compiled default is, is what we get.
# Tracking upstream — if vLLM grows session-level knobs later we can
# re-introduce REALTIME_STT_DELAY_MS here.

# 45000 (~1h audio) was RealtimeSTT's vendor-suggested ceiling but is
# unreachable on L4 24GB once the model weights, vLLM workspace, and
# encoder cache are accounted for — KV cache for the full window
# alone wants ~10GB. With --no-enable-chunked-prefill the prefill
# workspace eats another chunk, dropping the fit-able ceiling to
# ~9800. 8000 (~10 min) gives clean headroom. Bump via env when
# running on bigger GPUs (L40S 48GB / A100 80GB can take 30000+).
# In baseline mode the session runs unbounded until client reset, so
# this also bounds how long a single recording can run before vLLM
# itself errors out for exceeding the context window.
MAX_MODEL_LEN = int(os.environ.get("VLLM_MAX_MODEL_LEN", "8000"))
MAX_NUM_SEQS = int(os.environ.get("VLLM_MAX_NUM_SEQS", "16"))
# With chunked prefill disabled (see --no-enable-chunked-prefill in the
# vLLM args below), each prefill has to fit in one scheduler step, so
# max_num_batched_tokens must be >= max_model_len or vLLM refuses to
# start with "max_num_batched_tokens is smaller than max_model_len".
# Auto-bump so VLLM_MAX_MODEL_LEN can be set independently without
# having to keep the two env vars in sync.
MAX_NUM_BATCHED_TOKENS = max(
    int(os.environ.get("VLLM_MAX_NUM_BATCHED_TOKENS", "512")),
    MAX_MODEL_LEN,
)

# Print every upstream event type + timestamp to stdout. Off by default
# (noisy). Flip on via env when diagnosing streaming latency — pairs
# with vLLM's own engine logger ("Avg generation throughput: ...") to
# tell whether deltas are arriving steadily, in bursts, or not at all.
DEBUG_UPSTREAM = os.environ.get("REALTIME_STT_DEBUG_UPSTREAM", "0") not in ("0", "", "false", "False")

internal_key = os.environ.get("RELAY_INTERNAL_KEY", "")
internal_key_prev = os.environ.get("RELAY_INTERNAL_KEY_PREV", "")


# ── vLLM subprocess bring-up ──────────────────────────────────────────────────
# vLLM is a separate process so /admin/reload (which SIGTERMs us) doesn't
# trigger a model reload. On the next entrypoint loop iteration we detect
# the surviving vLLM via /v1/models and reuse it.

def _vllm_running() -> bool:
    try:
        return httpx.get(
            f"http://{VLLM_HOST}:{VLLM_PORT}/v1/models", timeout=2.0
        ).status_code == 200
    except Exception:
        return False


if _vllm_running():
    print(f"vLLM already running on :{VLLM_PORT}, reusing")
else:
    print(f"Starting vLLM with {MODEL_TAG} …")
    subprocess.Popen([
        "python3", "-m", "vllm.entrypoints.openai.api_server",
        "--model", MODEL_TAG,
        "--port", str(VLLM_PORT),
        # RealtimeSTT's Mistral-format weights require all three of these
        # flags; without them vLLM tries to load via the generic
        # HuggingFace path and fails on the config schema.
        "--tokenizer-mode", "mistral",
        "--config-format", "mistral",
        "--load-format", "mistral",
        "--trust-remote-code",
        # PIECEWISE cudagraph mode is what the RealtimeSTT Realtime model
        # was validated against (Red Hat AI day-1 guide). FULL_AND_PIECEWISE
        # crashes during compile on some L4/L40S drivers.
        "--compilation-config", '{"cudagraph_mode":"PIECEWISE"}',
        # On-the-fly INT4 quantization via bitsandbytes NF4. Picked
        # over fp8 because A5000 (Ampere) has no native FP8 tensor
        # cores — vLLM's FP8-Marlin fallback there is weight-only and
        # the dequant cost cancels the compute saving (RTF unchanged).
        # INT4 W4A16-Marlin on Ampere is different: weights are 4× smaller
        # so the per-GEMM workload genuinely drops, giving real ~2-3×
        # throughput plus 75% memory reduction. No precomputed weights
        # required; vLLM converts at load time.
        # Caveat: bitsandbytes typically expects HF-format weights and
        # may conflict with --load-format mistral. If startup fails
        # with "bitsandbytes requires HuggingFace format" or similar,
        # fall back to a precomputed AWQ checkpoint (llm-compressor)
        # with --quantization awq_marlin and the audio encoder
        # explicitly kept at BF16 via the recipe's ignore patterns.
        "--quantization", "bitsandbytes",
        "--max-model-len", str(MAX_MODEL_LEN),
        "--max-num-batched-tokens", str(MAX_NUM_BATCHED_TOKENS),
        "--max-num-seqs", str(MAX_NUM_SEQS),
        # gpu-memory-utilization left at vLLM's default (0.9); we used
        # to set it explicitly to the same value, which was dead code.
    ])

    # RealtimeSTT first boot: weight load + CUDA-graph capture takes longer
    # than a chat model. Give it 15min before declaring failure.
    deadline = time.time() + 900
    ready = False
    while time.time() < deadline:
        if _vllm_running():
            ready = True
            break
        time.sleep(2)
    if not ready:
        raise RuntimeError(
            f"vLLM did not become ready on port {VLLM_PORT} within 15min"
        )

print(f"vLLM Realtime ready at {VLLM_REALTIME_URL}")


# ── auth (identical to runpod_stt) ────────────────────────────────────────────

def _verify_hmac_token(token: str) -> bool:
    parts = token.split(":")
    if len(parts) != 3:
        return False
    uid, exp_str, sig = parts
    try:
        if time.time() > int(exp_str):
            return False
    except ValueError:
        return False
    payload = f"{uid}:{exp_str}".encode()
    for k in [internal_key, internal_key_prev]:
        if not k:
            continue
        expected = hmac_mod.new(k.encode(), payload, hashlib.sha256).hexdigest()
        if hmac_mod.compare_digest(sig, expected):
            return True
    return False


def _valid_key(key: str) -> bool:
    if not internal_key:
        return False
    if key == internal_key or (internal_key_prev and key == internal_key_prev):
        return True
    return _verify_hmac_token(key)


def _static_key_only(key: str) -> bool:
    if not internal_key:
        return False
    return key == internal_key or (internal_key_prev and key == internal_key_prev)


# ── audio + event conversion ──────────────────────────────────────────────────

def f32_bytes_to_pcm16_base64(audio_bytes: bytes) -> str:
    """Client sends raw f32 LE PCM 16kHz mono; vLLM Realtime expects
    base64-encoded PCM16 16kHz mono. The clip is mandatory — float
    samples outside [-1, 1] would wrap on the int16 cast and produce
    sawtooth noise that obliterates the encoder."""
    f32 = np.frombuffer(audio_bytes, dtype=np.float32)
    if f32.size == 0:
        return ""
    clipped = np.clip(f32, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    return base64.b64encode(pcm16.tobytes()).decode("ascii")


def _session_update_payload() -> dict:
    """vLLM Realtime's session.update only validates `model` at the top
    level — see RealtimeConnection.handle_event in vLLM v0.21.0. Anything
    else (modalities, input_audio_format, language, …) is unrecognized
    and triggers `Missing required field: model` because the validator
    only ever does `event.get("model")` on the event itself, not on
    `event["session"]`. So this is the minimal valid payload."""
    return {"type": "session.update", "model": MODEL_TAG}


def _commit_payload(final: bool) -> dict:
    """`final=False` is what *starts* a generation task — the upstream
    audio_queue is not consumed until this fires. `final=True` puts a
    None sentinel on the queue, ending the current generation and
    flushing a `transcription.done` event. So a long live session is
    really: commit(false) → many appends → commit(true) → commit(false)
    → … per utterance."""
    return {"type": "input_audio_buffer.commit", "final": final}


# ── session tracking ──────────────────────────────────────────────────────────

_active_sessions = 0
_active_sessions_lock = threading.Lock()


def _incr_sessions(delta: int) -> None:
    global _active_sessions
    with _active_sessions_lock:
        _active_sessions += delta


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="RealtimeSTT STT Adapter (RunPod)")


@app.get("/health")
async def health(x_internal_key: str = Header(default="")):
    if not _static_key_only(x_internal_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return {"status": "ok", "model": MODEL_TAG}


@app.get("/metrics")
async def metrics(x_internal_key: str = Header(default="")):
    if not _static_key_only(x_internal_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    cur_rss_kb = 0
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    cur_rss_kb = int(line.split()[1])
                    break
    except OSError:
        pass
    return {
        "rss_mb": round(cur_rss_kb / 1024, 1),
        "rss_peak_mb": round(peak_rss_kb / 1024, 1),
        "active_sessions": _active_sessions,
        "gc_counts": gc.get_count(),
        "vllm_realtime_url": VLLM_REALTIME_URL,
        "adapter_version": "baseline-v1",
    }


@app.post("/admin/reload")
async def admin_reload(x_internal_key: str = Header(default="")):
    """Exit so entrypoint.sh re-pulls fresh server.py and restarts.
    The vLLM subprocess survives (separate process group) and the next
    boot's _vllm_running() probe reuses it — reload is ~2s, not the
    full ~3min model warm-up."""
    if not _static_key_only(x_internal_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    loop = asyncio.get_running_loop()
    loop.call_later(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"status": "reloading"}


# ── streaming bridge ──────────────────────────────────────────────────────────

class _SessionState:
    """Per-WS-client running text. RealtimeSTT streams `transcription.delta`
    events whose `delta` field carries only the NEW tokens; we
    concatenate them into `running_text` and emit the cumulative form
    each frame so the existing Tauri client (which expects each partial
    frame to contain the full utterance-so-far, not just the latest
    increment) sees the contract it knows from CNN STT."""

    __slots__ = ("running_text", "last_emitted")

    def __init__(self) -> None:
        self.running_text = ""
        self.last_emitted = ""


async def _open_upstream() -> websockets.WebSocketClientProtocol:
    """Open a fresh vLLM Realtime WS, validate the model, and kick off
    the generation task — matching Mistral's reference client exactly:

        await ws.recv()                          # session.created
        await ws.send(session.update {model})    # model validation
        await ws.send(input_audio_buffer.commit) # start generation

    The commit fires immediately, before any audio is queued. vLLM's
    RealtimeSTT handler will briefly log a "Realtime model received empty
    multimodal embeddings" warning until the first audio frames arrive,
    but the embed_input_ids() fallback returns zero embeddings and the
    engine recovers transparently once real audio shows up. The
    reference client ships this exact ordering, so this is the
    intended path — earlier defensive buffering was over-engineering."""
    upstream = await websockets.connect(
        VLLM_REALTIME_URL,
        max_size=None,
        ping_interval=20,
        ping_timeout=20,
        open_timeout=10,
    )
    # Drain the session.created handshake so the next recv on the
    # caller side starts with model-level events.
    await upstream.recv()
    await upstream.send(json.dumps(_session_update_payload()))
    await upstream.send(json.dumps(_commit_payload(final=False)))
    return upstream


@app.websocket("/")
async def ws_endpoint(ws: WebSocket, key: str = Query("")):
    """Baseline adapter — matches Mistral's reference Realtime client
    1:1 except for the audio-format conversion (f32 LE → base64 PCM16)
    and the protocol envelope ({text, is_partial} vs raw deltas).

    What we deliberately do NOT do anymore (all of these were earlier
    speculative fixes that were piled on without isolating which one
    helped):
      - No audio batching at the adapter layer (forward each chunk as
        one input_audio_buffer.append).
      - No kickoff threshold (commit fires immediately in _open_upstream,
        exactly like the reference Gradio client).
      - No periodic flush (single long-running generation per session;
        if KV cache eventually slows it down, that's a vLLM/model
        property to surface, not for us to paper over).
      - No transcription.done auto-restart (if vLLM emits done on its
        own — max_tokens, model EOS — we forward it as a real final
        and tear down; the client reconnects).

    On client `{cmd: reset}` we close the upstream WS and reopen — a
    fresh vLLM session is the simplest way to flush all server-side
    state without the commit-cycle race we hit earlier."""
    if not _valid_key(key):
        await ws.close(code=1008, reason="unauthorized")
        return
    await ws.accept()
    _incr_sessions(1)

    state = _SessionState()
    try:
        upstream = await _open_upstream()
    except Exception as exc:
        _incr_sessions(-1)
        await ws.close(code=1011, reason=f"upstream unavailable: {exc}")
        return

    # asyncio.Event used to signal a reset from the client task to the
    # upstream-reader task. The reader can't safely close the upstream
    # itself (would race with the writer mid-send), so we hand off via
    # this event; the writer owns the upstream and does the swap.
    reset_signal = asyncio.Event()

    async def client_to_upstream():
        """Forward each incoming audio chunk as one append. Reset
        closes+reopens the upstream — simplest way to get a clean vLLM
        state without the commit-cycle dance."""
        nonlocal upstream
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=IDLE_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                return
            if msg["type"] == "websocket.disconnect":
                return
            if "text" in msg and msg["text"] is not None:
                try:
                    if json.loads(msg["text"]).get("cmd") == "reset":
                        # Emit whatever we accumulated as a final, then
                        # cycle the upstream. The reader task observes
                        # `reset_signal` and exits its recv() loop so
                        # we can safely close+reopen.
                        if state.running_text:
                            try:
                                await ws.send_text(json.dumps({
                                    "text": state.running_text,
                                    "is_partial": False,
                                }))
                            except Exception:
                                return
                        state.running_text = ""
                        state.last_emitted = ""
                        reset_signal.set()
                        try:
                            await upstream.close()
                        except Exception:
                            pass
                        try:
                            upstream = await _open_upstream()
                        except Exception as exc:
                            print(f"[realtime-stt] reset reopen failed: {exc}")
                            return
                        reset_signal.clear()
                except json.JSONDecodeError:
                    pass
                continue
            if "bytes" in msg and msg["bytes"] is not None:
                b64 = f32_bytes_to_pcm16_base64(msg["bytes"])
                if not b64:
                    continue
                try:
                    await upstream.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": b64,
                    }))
                except websockets.ConnectionClosed:
                    # Could be a reset-driven close — the writer will
                    # reopen and the next iteration picks up the new
                    # upstream via the `nonlocal` binding.
                    if reset_signal.is_set():
                        continue
                    return

    async def upstream_to_client():
        """Stream RealtimeSTT's transcription.delta into cumulative partial
        frames. transcription.done is treated as a final and ends the
        session — the reference client never sees done because it never
        sends commit(final:true), but if vLLM emits one for any reason
        (max_tokens, model EOS, error) we surface it cleanly."""
        nonlocal upstream
        while True:
            try:
                raw = await upstream.recv()
            except websockets.ConnectionClosed:
                # If client_to_upstream is mid-reset it will rebind
                # `upstream` shortly; spin on a short sleep until the
                # new one is up. Otherwise (true upstream death) exit.
                if reset_signal.is_set():
                    await asyncio.sleep(0.05)
                    continue
                return
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type", "")
            if DEBUG_UPSTREAM:
                _delta_len = len(evt.get("delta") or "")
                print(
                    f"[realtime-stt-upstream] {time.time():.3f} {etype} delta_len={_delta_len}",
                    flush=True,
                )

            if etype.endswith("transcription.delta") or etype == "response.audio_transcript.delta":
                delta = evt.get("delta") or evt.get("text") or ""
                if not delta:
                    continue
                state.running_text += delta
                if state.running_text != state.last_emitted:
                    state.last_emitted = state.running_text
                    try:
                        await ws.send_text(json.dumps({
                            "text": state.running_text,
                            "is_partial": True,
                        }))
                    except Exception:
                        return
                continue

            if etype.endswith("transcription.done") or etype == "response.audio_transcript.done":
                final = (
                    evt.get("transcript")
                    or evt.get("text")
                    or state.running_text
                )
                if final:
                    try:
                        await ws.send_text(json.dumps({
                            "text": final,
                            "is_partial": False,
                        }))
                    except Exception:
                        pass
                return

            if etype == "error":
                print(f"[realtime-stt] upstream error: {raw[:500]}")
                continue

    try:
        tasks = {
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        }
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await upstream.close()
        except Exception:
            pass
        _incr_sessions(-1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
