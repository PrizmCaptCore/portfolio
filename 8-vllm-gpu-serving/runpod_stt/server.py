"""
CNN STT streaming STT server — RunPod Pod deployment.

Protocol identical to modal_stt.py:
  Client → Server : binary frames  — raw f32 LE PCM, 16 kHz mono
  Server → Client : JSON text frame — {"text": "...", "is_partial": bool}
  Client → Server : JSON {"cmd": "reset"}

Auth: ?key=<HMAC-token-or-static-internal-key>
  RELAY_INTERNAL_KEY      current static key (also used to verify HMAC tokens)
  RELAY_INTERNAL_KEY_PREV previous static key (rolling update grace period)

Usage:
  python server.py [--host 0.0.0.0] [--port 8765]

RunPod Pod: expose port 8765, access via
  wss://<pod-id>-8765.proxy.runpod.net/?key=<token>
"""

import argparse
import asyncio
import gc
import hashlib
import hmac as hmac_mod
import json
import os
import queue
import resource
import signal
import threading
import time
from typing import Optional

import numpy as np
import torch
import nemo.collections.asr as nemo_asr
import uvicorn
from fastapi import FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

SAMPLE_RATE = 16_000
IDLE_TIMEOUT_SEC = 120

internal_key = os.environ.get("RELAY_INTERNAL_KEY", "")
internal_key_prev = os.environ.get("RELAY_INTERNAL_KEY_PREV", "")

STT_MODEL = os.environ["STT_MODEL"]  # HF model id; set by the Dockerfile ENV
print(f"Loading {STT_MODEL} …")
_device = "cuda" if torch.cuda.is_available() else "cpu"
_model = nemo_asr.models.ASRModel.from_pretrained(
    STT_MODEL,
    map_location=torch.device(_device),
)
_model.eval()
print(f"Model ready on {_device}")


# ── micro-batcher ─────────────────────────────────────────────────────────────

class _Batcher:
    """Funnels all concurrent transcribe requests through one worker
    thread that batches up to MAX_BATCH items per GPU call.

    Two problems this fixes at once:
      1. The encoder freeze/unfreeze race that fires when two threads
         call NeMo's transcribe() concurrently — only one thread ever
         drives the model, so there is no race.
      2. The throughput collapse a naive lock-around-transcribe causes:
         under load, partial transcribes serialize and eat all the
         budget so finals never make it out. Here finals are queued
         unconditionally and partials get dropped at submit time once
         the backlog exceeds PARTIAL_BACKPRESSURE, so finals always
         get through.

    Batching is via NeMo's native list-input transcribe([a0, a1, ...]).
    Different-length audio in the same batch is padded internally.
    """

    MAX_BATCH = 16
    MAX_WAIT_MS = 30
    PARTIAL_BACKPRESSURE = 16
    # Polling interval the worker uses while waiting for the first
    # item of a batch. Short enough to keep latency low when traffic
    # resumes; long enough that idle CPU is negligible. Combined with
    # IDLE_CLEANUP_AFTER below, this is also our idle-detector tick.
    IDLE_TICK_SEC = 5.0
    # After this much continuous idle, release PyTorch's CUDA cache so
    # VRAM that built up during a burst returns to the GPU. Without
    # this, the cache keeps holding the burst's peak allocation
    # indefinitely (CNN STT 0.6B alone is ~2.4GB but observed RSS
    # after a 200-session burst sits much higher).
    IDLE_CLEANUP_AFTER_SEC = 30.0

    def __init__(self, model):
        self._model = model
        self._queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True, name="stt-batcher").start()

    async def submit(self, audio: np.ndarray, is_final: bool) -> str:
        loop = asyncio.get_running_loop()
        if not is_final and self._queue.qsize() >= self.PARTIAL_BACKPRESSURE:
            return ""
        fut: asyncio.Future = loop.create_future()
        self._queue.put((audio, fut, loop))
        return await fut

    def _run(self) -> None:
        idle_since: Optional[float] = time.monotonic()
        while True:
            try:
                first = self._queue.get(timeout=self.IDLE_TICK_SEC)
                idle_since = None
            except queue.Empty:
                if idle_since is None:
                    idle_since = time.monotonic()
                elif (
                    time.monotonic() - idle_since >= self.IDLE_CLEANUP_AFTER_SEC
                ):
                    # Release Python refs and PyTorch's CUDA cache that
                    # accumulated during the prior burst. Reset the idle
                    # marker so we only do this once per idle period.
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    idle_since = float("inf")  # disable until next burst
                continue

            batch = [first]
            deadline = time.monotonic() + self.MAX_WAIT_MS / 1000.0
            while len(batch) < self.MAX_BATCH:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break

            audios = [item[0] for item in batch]
            try:
                with torch.no_grad():
                    results = self._model.transcribe(
                        audios,
                        batch_size=len(audios),
                        num_workers=0,
                    )
            except Exception as exc:
                for _, fut, loop in batch:
                    loop.call_soon_threadsafe(_set_exception, fut, exc)
                continue

            for (_, fut, loop), r in zip(batch, results):
                text = (r.text if hasattr(r, "text") else str(r)).strip()
                loop.call_soon_threadsafe(_set_result, fut, text)

            # Drop refs to the just-processed batch before we block on
            # the next get(). Without this, the last burst's audio
            # tensors and NeMo result objects sit in this thread's frame
            # locals throughout the idle period, blocking GC.
            del batch, audios, results


def _set_result(fut: asyncio.Future, value) -> None:
    if not fut.done():
        fut.set_result(value)


def _set_exception(fut: asyncio.Future, exc: BaseException) -> None:
    if not fut.done():
        fut.set_exception(exc)


_batcher = _Batcher(_model)


# ── session tracking ──────────────────────────────────────────────────────────
# Lightweight atomic counter for active WS sessions. Exposed by /metrics so
# we can see (a) does it return to 0 after load drains — if not, a session
# object is leaking — and (b) what concurrency was being held when memory
# growth was observed.

_active_sessions = 0
_active_sessions_lock = threading.Lock()


def _incr_sessions(delta: int) -> None:
    global _active_sessions
    with _active_sessions_lock:
        _active_sessions += delta


# ── auth ──────────────────────────────────────────────────────────────────────

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


# ── streaming session ─────────────────────────────────────────────────────────

class StreamingSession:
    SILENCE_RMS = 0.003
    SILENCE_FINAL_SEC = 0.6
    MIN_SPEECH_SEC = 0.2
    MAX_SPEECH_SEC = 8.0
    INTERIM_SEC = 0.6
    PRE_SPEECH_SEC = 0.15

    def __init__(self):
        self._pre_buf = np.array([], dtype=np.float32)
        self._reset()

    def _reset(self):
        self._audio = np.array([], dtype=np.float32)
        self._speech_started = False
        self._silence_since: Optional[float] = None
        self._last_interim = 0.0
        self._last_partial_text = ""

    def reset(self):
        self._reset()
        self._pre_buf = np.array([], dtype=np.float32)

    def feed_and_extract(self, samples: np.ndarray):
        """Update streaming state with incoming samples.

        Fast path: only mutates buffers and runs a cheap RMS check.
        Returns (audio_or_None, is_final). When audio is not None the
        caller should transcribe it on a worker thread and send the
        result. Transcription is *never* run on the event loop here, so
        ws.receive() keeps draining bytes while a previous utterance is
        still being decoded — that was the root cause of words
        disappearing at sentence boundaries (blocking transcribe stalled
        the receive loop, TCP bytes queued up, and the first word of
        the next utterance ended up mashed onto the trailing silence of
        the previous one).
        """
        rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
        now = time.monotonic()

        if rms >= self.SILENCE_RMS:
            self._silence_since = None
            if not self._speech_started:
                self._speech_started = True
                self._last_interim = now
                if len(self._pre_buf) > 0:
                    self._audio = np.concatenate([self._pre_buf, samples])
                    self._pre_buf = np.array([], dtype=np.float32)
                else:
                    self._audio = samples.copy()
            else:
                self._audio = np.concatenate([self._audio, samples])

            if len(self._audio) / SAMPLE_RATE >= self.MAX_SPEECH_SEC:
                return self._extract_final()
            if now - self._last_interim >= self.INTERIM_SEC:
                self._last_interim = now
                return (self._audio.copy(), False)
        else:
            if self._speech_started:
                self._audio = np.concatenate([self._audio, samples])
                if self._silence_since is None:
                    self._silence_since = now
                elif now - self._silence_since >= self.SILENCE_FINAL_SEC:
                    if len(self._audio) / SAMPLE_RATE >= self.MIN_SPEECH_SEC:
                        return self._extract_final()
                    self._reset()
            else:
                max_pre = int(self.PRE_SPEECH_SEC * SAMPLE_RATE)
                self._pre_buf = np.concatenate([self._pre_buf, samples])
                if len(self._pre_buf) > max_pre:
                    self._pre_buf = self._pre_buf[-max_pre:]
        return (None, False)

    def _extract_final(self):
        """Snapshot audio for a final, trim trailing silence, reset state."""
        audio = self._audio.copy()
        # Strip the trailing silence that accumulated before the endpoint
        # fired — otherwise CNN STT sometimes hallucinates a word from
        # the dead air or clips the last real word.
        silence_trim = int(SAMPLE_RATE * self.SILENCE_FINAL_SEC)
        if len(audio) > silence_trim + int(SAMPLE_RATE * self.MIN_SPEECH_SEC):
            audio = audio[:-silence_trim]
        self._reset()
        return (audio, True)

    async def transcribe(self, audio: np.ndarray, is_final: bool) -> str:
        """Submit a transcribe request to the shared batcher. Returns
        the empty string for sub-MIN_SPEECH_SEC audio or for partials
        that get shed under backpressure."""
        if len(audio) < int(SAMPLE_RATE * self.MIN_SPEECH_SEC):
            return ""
        return await _batcher.submit(audio, is_final=is_final)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="CNN STT STT Server (RunPod)")


@app.get("/health")
async def health(x_internal_key: str = Header(default="")):
    if not _static_key_only(x_internal_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return {"status": "ok"}


@app.get("/metrics")
async def metrics(x_internal_key: str = Header(default="")):
    """Memory + load metrics for capacity / leak debugging. Compare
    snapshots before / during / after a stress run to see whether RSS
    or GPU memory hangs around after load drops. Numbers to watch:

      - rss_mb: process resident set size (peak; never decreases —
        Linux ru_maxrss is high-watermark, not current)
      - active_sessions: should return to 0 when all WS connections
        close. If not, ws_endpoint is leaking a session reference.
      - batcher_queue_depth: should be 0 when idle.
      - cuda_allocated_mb: live tensors. Returning to baseline after
        load means no Python-side leak of CUDA tensors.
      - cuda_reserved_mb: PyTorch's CUDA cache. Stays high after load;
        not a leak. empty_cache() can release it but that has cost.
      - gc_counts: per-generation pending objects. Steady-state is fine.
    """
    if not _static_key_only(x_internal_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    # ru_maxrss is peak high-watermark (KB on Linux); never decreases.
    # /proc/self/status:VmRSS is the *current* resident set, which is
    # what shows whether load actually drained from memory.
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
    body = {
        "rss_mb": round(cur_rss_kb / 1024, 1),
        "rss_peak_mb": round(peak_rss_kb / 1024, 1),
        "active_sessions": _active_sessions,
        "batcher_queue_depth": _batcher._queue.qsize(),
        "gc_counts": gc.get_count(),
    }
    if torch.cuda.is_available():
        body["cuda_allocated_mb"] = round(torch.cuda.memory_allocated() / 1024**2, 1)
        body["cuda_reserved_mb"] = round(torch.cuda.memory_reserved() / 1024**2, 1)
    return body


@app.post("/admin/reload")
async def admin_reload(x_internal_key: str = Header(default="")):
    """Exit the process so entrypoint.sh pulls fresh code on its next
    loop iteration. Only the static RELAY_INTERNAL_KEY (not HMAC user
    tokens) is accepted, to keep this off the user-facing auth surface.
    The exit is deferred so this HTTP response can flush first."""
    if not _static_key_only(x_internal_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    # SIGTERM lets uvicorn drain inflight WS / HTTP connections (up to
    # ~5s) before exiting, so partial transcribes finish instead of
    # being abruptly dropped. entrypoint.sh's loop then re-pulls and
    # restarts.
    loop = asyncio.get_running_loop()
    loop.call_later(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"status": "reloading"}


@app.websocket("/")
async def ws_endpoint(ws: WebSocket, key: str = Query("")):
    """Split receive and transcribe into cooperating tasks.

    The receive task owns the WebSocket and is always ready to pull
    bytes as they arrive — it never awaits GPU work. The processor task
    owns the session buffer, decides when to emit a partial/final, and
    awaits the shared batcher for transcription. Splitting the two is
    what prevents the boundary-word loss described in
    feed_and_extract().
    """
    if not _valid_key(key):
        await ws.close(code=1008, reason="unauthorized")
        return
    await ws.accept()
    session = StreamingSession()
    msg_q: asyncio.Queue = asyncio.Queue()
    _incr_sessions(1)

    async def receiver():
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=IDLE_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                await msg_q.put(("close", "idle"))
                return
            if msg["type"] == "websocket.disconnect":
                await msg_q.put(("close", "disconnect"))
                return
            if "text" in msg and msg["text"] is not None:
                await msg_q.put(("text", msg["text"]))
                continue
            if "bytes" in msg and msg["bytes"] is not None:
                await msg_q.put(("bytes", msg["bytes"]))

    async def processor():
        while True:
            kind, payload = await msg_q.get()
            if kind == "close":
                return
            if kind == "text":
                try:
                    if json.loads(payload).get("cmd") == "reset":
                        session.reset()
                except json.JSONDecodeError:
                    pass
                continue
            if kind != "bytes":
                continue
            samples = np.frombuffer(payload, dtype=np.float32).copy()
            audio, is_final = session.feed_and_extract(samples)
            if audio is None:
                continue
            # Submit to the shared batcher. receiver() keeps draining
            # WS bytes into `queue` during this await so audio that
            # arrived *during* the decode isn't lost — next
            # feed_and_extract will see it in the session buffer (or
            # as the start of the next utterance).
            text = await session.transcribe(audio, is_final=is_final)
            if not text:
                continue
            if is_final:
                await ws.send_text(json.dumps({"text": text, "is_partial": False}))
            else:
                if text != session._last_partial_text:
                    session._last_partial_text = text
                    await ws.send_text(
                        json.dumps({"text": text, "is_partial": True})
                    )

    try:
        r_task = asyncio.create_task(receiver())
        p_task = asyncio.create_task(processor())
        done, pending = await asyncio.wait(
            {r_task, p_task},
            return_when=asyncio.FIRST_COMPLETED,
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
        _incr_sessions(-1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
