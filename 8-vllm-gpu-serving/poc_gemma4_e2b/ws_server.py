"""
Gemma 4 E2B WebSocket STT server — PoC.

Protocol identical to runpod_stt/server.py (the CNN STT reference):
  Client → Server : binary frames — f32 LE PCM, 16 kHz mono
  Server → Client : JSON text     — {"text": "...", "is_partial": bool}
  Client → Server : JSON          — {"cmd": "reset"}

Difference from CNN STT streaming: token-level streaming.
  - During an utterance, the server only accumulates audio (no partial emit).
  - At VAD final, generation kicks off via TextIteratorStreamer in a
    thread; each new token triggers a {"text": <accumulated>, "is_partial": true}
    push.
  - When generation finishes, one {"text": <accumulated>, "is_partial": false}
    is sent to close the row on the client side.
  - `text` is always the *full accumulated* text, never a delta — matches the
    relay-client NemoProvider expectations (it overwrites the row on
    every push, so deltas would flicker).

Auth: `?key=<token>` query param.
  - RELAY_INTERNAL_KEY empty → auth disabled entirely (PoC default).
  - RELAY_INTERNAL_KEY set    → static-key or HMAC token validation, matching
    runpod_stt/server.py and apps/ai_gateway/views.py.

Mode: ASR-only (Korean speech -> Korean text). AST (translation) was
removed from this endpoint per handoff Q5 -- mixing the two prompts in a
single server let Gemma 4 occasionally emit English in ASR mode.
Translation belongs to the production gateway as a separate concern.

Env vars:
  MODEL_ID                 default: google/gemma-4-E2B-it (swap to E4B if needed)
  STT_LANG                 source-language hint. "" (default) = auto-detect.
                           Set to "Korean" / "English" only when you KNOW the
                           audio language -- forcing a wrong language makes
                           the model hallucinate glyphs in the target script.
  RELAY_INTERNAL_KEY       optional, enables auth when set
  RELAY_INTERNAL_KEY_PREV  optional, rolling-update grace key
  HF_TOKEN                 required for the gated Gemma 4 weights

Usage (inside intelanalytics/ipex-llm-xpu container):
  pip install -U transformers librosa accelerate soundfile fastapi uvicorn websockets
  python ws_server.py --host 0.0.0.0 --port 8765
"""

import argparse
import asyncio
import hashlib
import hmac as hmac_mod
import json
import os
import tempfile
import threading
import time
from typing import Optional

import numpy as np
import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from transformers import AutoModelForMultimodalLM, AutoProcessor, TextIteratorStreamer

SAMPLE_RATE = 16_000
IDLE_TIMEOUT_SEC = 120

MODEL_ID = os.environ.get("MODEL_ID", "google/gemma-4-E2B-it")

# STT_LANG controls the source-language hint in the ASR prompt.
#   "" / unset -> auto-detect (use this for mixed-language meetings)
#   "Korean"   -> force Korean source (model will hallucinate Korean if it
#                 hears English -- only use when you KNOW the audio is Korean)
#   "English"  -> force English source (mirror image of the above)
#
# Lesson from earlier run: a hard "Korean -> Korean text" prompt on English
# audio made Gemma 4 emit Korean glyphs for English utterances and mix the
# two mid-sentence. The auto variant ("same language as the spoken audio")
# avoids that conflict entirely.
STT_LANG = os.environ.get("STT_LANG", "").strip()

# Translation (AST) is intentionally NOT exposed at this endpoint per
# handoff Q5: mixing two prompts in one server let the model blur task
# boundaries. Translation is the production gateway's concern.
ASR_NUMBER_RULE = (
    "* When transcribing numbers, write the digits, i.e. write 1.7 and "
    "not one point seven, and write 3 instead of three."
)
ASR_AUTO = (
    "Transcribe the following speech segment.\n"
    "Output the transcription in the same language as the spoken audio.\n"
    "\n"
    "Follow these specific instructions for formatting the answer:\n"
    "* Only output the transcription, with no newlines.\n"
    "* Do NOT translate to any other language.\n"
    f"{ASR_NUMBER_RULE}"
)
ASR_FIXED_TMPL = (
    "Transcribe the following speech segment in {lang} into {lang} text.\n"
    "\n"
    "Follow these specific instructions for formatting the answer:\n"
    "* Only output the transcription, with no newlines.\n"
    f"{ASR_NUMBER_RULE}"
)

internal_key = os.environ.get("RELAY_INTERNAL_KEY", "")
internal_key_prev = os.environ.get("RELAY_INTERNAL_KEY_PREV", "")


def pick_device() -> str:
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


print(f"[init] loading {MODEL_ID} ...", flush=True)
_device = pick_device()
print(f"[init] device={_device}", flush=True)
_processor = AutoProcessor.from_pretrained(MODEL_ID)
# bfloat16 explicit: dtype="auto" picks the config default which can be fp32
# for some Gemma 4 checkpoints. Arc B580 has 12GB; fp32 weights alone (~8GB)
# leave almost no room for KV cache + audio features and OOM after one
# generate. bf16 cuts weights in half and Arc supports it natively.
_model = AutoModelForMultimodalLM.from_pretrained(
    MODEL_ID, dtype=torch.bfloat16, device_map=_device
)
_model.eval()
_mode_label = f"ASR (forced={STT_LANG})" if STT_LANG else "ASR (auto-detect language)"
print(f"[init] model ready on {_device}, task={_mode_label}", flush=True)


def _build_prompt() -> str:
    if STT_LANG:
        return ASR_FIXED_TMPL.format(lang=STT_LANG)
    return ASR_AUTO


# ── auth (mirrors runpod_stt/server.py) ───────────────────────────────────────

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
    # PoC convenience: empty RELAY_INTERNAL_KEY disables auth so the client
    # can connect with no `?key=` at all. Production must set the key.
    if not internal_key:
        return True
    if key == internal_key or (internal_key_prev and key == internal_key_prev):
        return True
    return _verify_hmac_token(key)


# ── VAD / accumulation ────────────────────────────────────────────────────────

class StreamingSession:
    """Audio accumulator with simple RMS-based VAD.

    feed() returns the accumulated audio np.ndarray on a VAD endpoint
    (or MAX_SPEECH_SEC cap), otherwise None. Gemma 4 generate runs once
    per endpoint -- no mid-utterance interim re-decode -- because token-
    level streaming after final is the intended Gemma 4 UX (see handoff).
    """

    SILENCE_RMS = 0.003
    SILENCE_FINAL_SEC = 0.6
    MIN_SPEECH_SEC = 0.2
    # Gemma 4 hard limit is 30s. We cap further to keep encoder work bounded.
    MAX_SPEECH_SEC = 8.0
    PRE_SPEECH_SEC = 0.15

    def __init__(self):
        self._pre_buf = np.array([], dtype=np.float32)
        self._reset()

    def _reset(self):
        self._audio = np.array([], dtype=np.float32)
        self._speech_started = False
        self._silence_since: Optional[float] = None

    def reset(self):
        self._reset()
        self._pre_buf = np.array([], dtype=np.float32)

    def feed(self, samples: np.ndarray) -> Optional[np.ndarray]:
        """Accumulate samples. Return audio np.ndarray on VAD final, else None."""
        rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
        now = time.monotonic()

        if rms >= self.SILENCE_RMS:
            self._silence_since = None
            if not self._speech_started:
                self._speech_started = True
                if len(self._pre_buf) > 0:
                    self._audio = np.concatenate([self._pre_buf, samples])
                    self._pre_buf = np.array([], dtype=np.float32)
                else:
                    self._audio = samples.copy()
            else:
                self._audio = np.concatenate([self._audio, samples])

            if len(self._audio) / SAMPLE_RATE >= self.MAX_SPEECH_SEC:
                return self._extract_final()
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
        return None

    def _extract_final(self) -> np.ndarray:
        audio = self._audio.copy()
        silence_trim = int(SAMPLE_RATE * self.SILENCE_FINAL_SEC)
        if len(audio) > silence_trim + int(SAMPLE_RATE * self.MIN_SPEECH_SEC):
            audio = audio[:-silence_trim]
        self._reset()
        return audio


# ── inference ────────────────────────────────────────────────────────────────

async def _stream_tokens(ws: WebSocket, audio: np.ndarray) -> None:
    """Run Gemma 4 generation in a worker thread, push accumulated text on
    every new token. asyncio.to_thread bridges the blocking streamer iterator
    so the WS event loop keeps draining incoming audio in parallel.

    Timing log on each call (one [gen] line):
      audio  -- input audio length in seconds
      prep   -- chat-template build + processor .to(device) (CPU work, mostly)
      ttft   -- VAD-final -> first token (audio encoder + prefill + first sample).
                This is the user-visible "speak ends, screen still blank" delay.
      total  -- VAD-final -> last token finished generating
      tokens -- number of streamed tokens
      tok/s  -- total / tokens
    """
    audio_sec = len(audio) / SAMPLE_RATE
    t_start = time.perf_counter()
    prep_ms: Optional[float] = None
    ttft_ms: Optional[float] = None
    n_tokens = 0

    # Processor's chat template takes a path; cheapest is a temp wav.
    # In-memory paths via BytesIO are not consistent across processor versions.
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio, SAMPLE_RATE)
        audio_path = tmp.name

    try:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": audio_path},
                    {"type": "text", "text": _build_prompt()},
                ],
            }
        ]
        inputs = _processor.apply_chat_template(
            messages,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            add_generation_prompt=True,
        ).to(_model.device)
        prep_ms = (time.perf_counter() - t_start) * 1000.0

        streamer = TextIteratorStreamer(
            _processor.tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        gen_thread = threading.Thread(
            target=_model.generate,
            kwargs=dict(**inputs, max_new_tokens=256, streamer=streamer),
        )
        gen_thread.start()

        accumulated = ""
        streamer_iter = iter(streamer)

        def next_or_none() -> Optional[str]:
            try:
                return next(streamer_iter)
            except StopIteration:
                return None

        while True:
            piece = await asyncio.to_thread(next_or_none)
            if piece is None:
                break
            if ttft_ms is None:
                ttft_ms = (time.perf_counter() - t_start) * 1000.0
            n_tokens += 1
            accumulated += piece
            await ws.send_text(
                json.dumps({"text": accumulated, "is_partial": True})
            )

        gen_thread.join()

        total_s = time.perf_counter() - t_start
        tok_per_s = (n_tokens / total_s) if total_s > 0 else 0.0
        print(
            f"[gen] audio={audio_sec:.2f}s "
            f"prep={prep_ms:.0f}ms "
            f"ttft={(ttft_ms if ttft_ms is not None else -1):.0f}ms "
            f"total={total_s:.2f}s "
            f"tokens={n_tokens} tok/s={tok_per_s:.1f}",
            flush=True,
        )

        # Final marker - is_partial=False bumps the client's sequence_id so
        # the next utterance starts a fresh row.
        if accumulated.strip():
            await ws.send_text(
                json.dumps({"text": accumulated, "is_partial": False})
            )
    finally:
        # XPU memory cleanup. Without this, Level Zero's allocator holds onto
        # the prior generate's KV cache + audio encoder tensors and the
        # second utterance OOMs with UR_RESULT_ERROR_OUT_OF_RESOURCES.
        # Python GC alone is not enough - empty_cache tells the allocator
        # to actually recycle freed blocks.
        try:
            del inputs
        except (NameError, UnboundLocalError):
            pass
        try:
            del streamer
        except (NameError, UnboundLocalError):
            pass
        try:
            del gen_thread
        except (NameError, UnboundLocalError):
            pass
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            try:
                torch.xpu.synchronize()
                torch.xpu.empty_cache()
            except Exception as e:
                print(f"[ws] xpu cache cleanup warning: {e}", flush=True)
        try:
            os.unlink(audio_path)
        except OSError:
            pass


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Gemma 4 E2B STT (PoC)")


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_ID, "device": _device, "task": "asr"}


@app.websocket("/")
async def ws_endpoint(ws: WebSocket, key: str = Query("")):
    """receiver/processor split so audio keeps streaming in while a generation
    is mid-flight — same pattern as runpod_stt/server.py.
    """
    print(f"[ws] connect attempt (key_len={len(key)})", flush=True)
    if not _valid_key(key):
        await ws.close(code=1008, reason="unauthorized")
        print("[ws] rejected (auth)", flush=True)
        return
    await ws.accept()
    print("[ws] connection open", flush=True)
    session = StreamingSession()
    queue: asyncio.Queue = asyncio.Queue()
    diag = {"first_audio": False, "total_samples": 0, "bytes_msgs": 0}

    async def receiver():
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=IDLE_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                await queue.put(("close", "idle"))
                return
            if msg["type"] == "websocket.disconnect":
                await queue.put(("close", "disconnect"))
                return
            if "text" in msg and msg["text"] is not None:
                await queue.put(("text", msg["text"]))
                continue
            if "bytes" in msg and msg["bytes"] is not None:
                await queue.put(("bytes", msg["bytes"]))

    async def processor():
        while True:
            kind, payload = await queue.get()
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
            diag["bytes_msgs"] += 1
            diag["total_samples"] += len(samples)
            if not diag["first_audio"] and len(samples) > 0:
                rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
                print(f"[ws] first audio: {len(samples)} samples, rms={rms:.4f}", flush=True)
                diag["first_audio"] = True
            # Heartbeat every ~5s of audio so silence vs no-flow is distinguishable.
            if diag["bytes_msgs"] % 100 == 0:
                rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
                print(
                    f"[ws] audio flowing: msgs={diag['bytes_msgs']} "
                    f"total={diag['total_samples']/SAMPLE_RATE:.1f}s rms={rms:.4f}",
                    flush=True,
                )
            audio = session.feed(samples)
            if audio is None:
                continue
            print(
                f"[ws] VAD final: {len(audio)/SAMPLE_RATE:.2f}s utterance "
                f"(after {diag['total_samples']/SAMPLE_RATE:.1f}s total) -> generate",
                flush=True,
            )
            diag["total_samples"] = 0
            try:
                await _stream_tokens(ws, audio)
                print("[ws] generate done", flush=True)
            except Exception as e:
                # Surface error to client and keep the session alive for the
                # next utterance — generation hiccups shouldn't kill the WS.
                try:
                    await ws.send_text(
                        json.dumps(
                            {"text": "", "is_partial": False, "error": str(e)}
                        )
                    )
                except Exception:
                    return

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
