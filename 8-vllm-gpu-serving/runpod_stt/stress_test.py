"""
Stress test for runpod_stt — exercises the full production path
(example.com gateway → RunPod STT Pod) the way relay-client
does it. Login with email/password, mint per-session STT tokens via
the gateway, then open N concurrent WebSocket sessions against the
Pod and push real audio + trailing silence to force a final.

What it verifies:
  - The encoder freeze/unfreeze race that fired with concurrent
    transcribe() calls (fixed by a model-level threading.Lock).
  - End-to-end production capacity: login → /stt/session/ →
    WSS audio stream → final transcript, all concurrent.

Required env (loaded from a .env in CWD or process env):
  ID, PW                          login credentials
  STT_GATEWAY_BASE (optional)     default https://api.example.com/api/v1

Usage (PowerShell):
  python stress_test.py `
      --audio "C:\\path\\to\\audio.mp4" `
      --sessions 100

Tip: ramp up — 4, 16, 64, 100 — and watch the latency curve. The
lock serializes decode on a single Pod, so per-session p50 ≈
N × decode_time at saturation. If that's too tall, look at the
mini-batcher / replica fan-out options in the project notes.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from typing import Optional
from urllib.parse import quote

import av
import httpx
import numpy as np
import websockets
from dotenv import load_dotenv


SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1280
TRAILING_SILENCE_SEC = 1.2
DEFAULT_GATEWAY = "https://api.example.com/api/v1"


def decode_to_pcm(path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    container = av.open(path)
    stream = next(s for s in container.streams if s.type == "audio")
    resampler = av.AudioResampler(format="flt", layout="mono", rate=sample_rate)
    pcm: list[np.ndarray] = []
    for frame in container.decode(stream):
        for out in resampler.resample(frame):
            pcm.append(out.to_ndarray().reshape(-1).astype(np.float32))
    for out in resampler.resample(None):
        pcm.append(out.to_ndarray().reshape(-1).astype(np.float32))
    container.close()
    return np.concatenate(pcm) if pcm else np.array([], np.float32)


async def login(client: httpx.AsyncClient, base: str, email: str, password: str) -> str:
    r = await client.post(
        f"{base}/auth/token/",
        json={"email": email, "password": password},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["access"]


async def mint_session(client: httpx.AsyncClient, base: str, jwt: str) -> tuple[str, str]:
    r = await client.post(
        f"{base}/ai/stt/session/",
        headers={"Authorization": f"Bearer {jwt}"},
        timeout=30.0,
    )
    r.raise_for_status()
    body = r.json()
    return body["url"], body["token"]


def build_ws_url(url: str, token: str) -> str:
    ws = url.replace("https://", "wss://").replace("http://", "ws://")
    if "?" in ws:
        ws = ws.split("?", 1)[0]
    if not ws.endswith("/"):
        ws = ws + "/"
    return f"{ws}?key={quote(token, safe='')}"


async def ws_session(
    sid: int,
    ws_url: str,
    audio: np.ndarray,
    speech_sec: float,
    final_wait_sec: float,
    barrier: asyncio.Barrier,
    results: dict,
) -> None:
    finals: list[dict] = []
    partials = 0
    errors: list[str] = []
    barrier_release_t: Optional[float] = None
    final_t: Optional[float] = None
    connect_t: Optional[float] = None

    try:
        connect_start = time.monotonic()
        async with websockets.connect(ws_url, max_size=2 ** 22) as ws:
            connect_t = (time.monotonic() - connect_start) * 1000
            await barrier.wait()
            barrier_release_t = time.monotonic()

            speech_n = int(speech_sec * SAMPLE_RATE)
            speech = audio[:speech_n]
            if len(speech) < speech_n:
                reps = speech_n // max(len(speech), 1) + 1
                speech = np.tile(speech, reps)[:speech_n]
            silence = np.zeros(int(TRAILING_SILENCE_SEC * SAMPLE_RATE), np.float32)
            pcm = np.concatenate([speech.astype(np.float32), silence])

            async def sender():
                chunk_dur = CHUNK_SAMPLES / SAMPLE_RATE
                next_send = time.monotonic()
                for off in range(0, len(pcm), CHUNK_SAMPLES):
                    chunk = pcm[off:off + CHUNK_SAMPLES]
                    await ws.send(chunk.tobytes())
                    next_send += chunk_dur
                    delay = next_send - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)

            async def receiver():
                nonlocal final_t, partials
                while True:
                    msg = await ws.recv()
                    if not isinstance(msg, str):
                        continue
                    try:
                        obj = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("is_partial") is False:
                        final_t = time.monotonic()
                        finals.append(obj)
                        return
                    if obj.get("is_partial") is True:
                        partials += 1

            send_task = asyncio.create_task(sender())
            recv_task = asyncio.create_task(receiver())
            try:
                await asyncio.wait_for(recv_task, timeout=final_wait_sec)
            except asyncio.TimeoutError:
                errors.append("timeout waiting for final")
                recv_task.cancel()
            finally:
                if not send_task.done():
                    send_task.cancel()
                    try:
                        await send_task
                    except (asyncio.CancelledError, Exception):
                        pass

    except websockets.ConnectionClosed as e:
        errors.append(f"closed code={e.code} reason={e.reason!r}")
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")

    latency_ms = None
    if barrier_release_t is not None and final_t is not None:
        latency_ms = (final_t - barrier_release_t) * 1000

    results[sid] = {
        "finals": finals,
        "partials": partials,
        "errors": errors,
        "latency_ms": latency_ms,
        "connect_ms": connect_t,
    }


async def main_async(args):
    load_dotenv()
    email = args.email or os.environ.get("ID")
    password = args.password or os.environ.get("PW")
    if not (email and password):
        raise SystemExit("ID/PW not set (use --email/--password or env via .env)")
    base = args.gateway or os.environ.get("STT_GATEWAY_BASE", DEFAULT_GATEWAY)

    print(f"Decoding {args.audio} …", flush=True)
    audio = decode_to_pcm(args.audio)
    print(f"  {len(audio) / SAMPLE_RATE:.1f}s @ 16kHz mono float32", flush=True)

    async with httpx.AsyncClient(verify=True) as http:
        t0 = time.monotonic()
        print(f"Login {email} → {base}/auth/token/", flush=True)
        jwt = await login(http, base, email, password)
        print(f"  jwt acquired ({(time.monotonic() - t0) * 1000:.0f}ms)", flush=True)

        print(f"Minting {args.sessions} STT tokens via {base}/ai/stt/session/", flush=True)
        mint_start = time.monotonic()
        # Mint sequentially with mild concurrency to avoid hammering the
        # gateway; if this throttles in practice we can adjust.
        sem = asyncio.Semaphore(args.mint_concurrency)

        async def _mint(i: int):
            async with sem:
                try:
                    url, tok = await mint_session(http, base, jwt)
                    return i, url, tok, None
                except Exception as e:
                    return i, None, None, f"{type(e).__name__}: {e}"

        minted = await asyncio.gather(*(_mint(i) for i in range(args.sessions)))
        mint_ms = (time.monotonic() - mint_start) * 1000
        ok = [m for m in minted if m[3] is None]
        bad = [m for m in minted if m[3] is not None]
        print(
            f"  minted {len(ok)}/{args.sessions} in {mint_ms:.0f}ms",
            flush=True,
        )
        for i, _, _, err in bad[:5]:
            print(f"    s{i:03d}: MINT ERROR {err}", flush=True)
        if not ok:
            raise SystemExit("no sessions minted, aborting")

    # Build WS URLs and run concurrent sessions.
    sessions = [(i, build_ws_url(url, tok)) for i, url, tok, _ in ok]
    pod_urls = {s[1].split("?")[0] for s in sessions}
    print(f"  Pod URLs in this run: {pod_urls}", flush=True)

    # Expected wall-clock to first final = min(speech_sec, MAX_SPEECH_SEC=8s)
    # for the server-side forced-final case, plus a few seconds for the
    # batcher + decode + network. A timeout sized just above that lets
    # us fail fast when the Pod is saturated — without it, dead sessions
    # sit waiting the full 60s and the test wastes minutes per overload.
    if args.final_timeout > 0:
        final_wait_sec = args.final_timeout
    else:
        final_wait_sec = min(args.speech_sec, 8.0) + 8.0
    print(
        f"Opening {len(sessions)} concurrent WS sessions "
        f"(speech={args.speech_sec:.1f}s, final timeout={final_wait_sec:.0f}s)",
        flush=True,
    )
    barrier = asyncio.Barrier(len(sessions))
    results: dict = {}
    await asyncio.gather(
        *(
            ws_session(
                i, ws_url, audio, args.speech_sec, final_wait_sec, barrier, results
            )
            for i, ws_url in sessions
        )
    )

    finals_ok = 0
    errored = 0
    latencies: list[float] = []
    connects: list[float] = []
    error_counts: dict[str, int] = {}
    for sid in sorted(results):
        r = results[sid]
        if r.get("connect_ms") is not None:
            connects.append(r["connect_ms"])
        if r.get("errors"):
            errored += 1
            key = r["errors"][0][:80]
            error_counts[key] = error_counts.get(key, 0) + 1
            continue
        if r.get("finals"):
            finals_ok += 1
            lat = r.get("latency_ms")
            if lat is not None:
                latencies.append(lat)

    print()
    print("== summary ==")
    print(f"  sessions     : {len(sessions)}")
    print(f"  finals OK    : {finals_ok}")
    print(f"  errors       : {errored}")
    if connects:
        print(
            f"  ws connect   : p50={statistics.median(connects):.0f}ms  "
            f"max={max(connects):.0f}ms"
        )
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) >= 20 else max(latencies)
        print(
            f"  final latency: p50={p50:.0f}ms  p95={p95:.0f}ms  max={max(latencies):.0f}ms"
        )
    if error_counts:
        print("  error breakdown:")
        for k, v in sorted(error_counts.items(), key=lambda x: -x[1]):
            print(f"    [{v}x] {k}")
    if errored > 0 or finals_ok != len(sessions):
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--sessions", type=int, default=8)
    ap.add_argument("--speech-sec", type=float, default=4.0,
                    help="Seconds of speech to send per session "
                         "(server forces a final every MAX_SPEECH_SEC=8s, "
                         "so speech > 8s yields multiple finals; client "
                         "still returns on the first final received)")
    ap.add_argument("--email", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--gateway", default="",
                    help=f"Override gateway base (default {DEFAULT_GATEWAY})")
    ap.add_argument("--mint-concurrency", type=int, default=8,
                    help="Parallel /stt/session/ requests when minting tokens")
    ap.add_argument("--final-timeout", type=float, default=0.0,
                    help="Seconds to wait for first final per session "
                         "(0 = auto from speech-sec; default scales as "
                         "min(speech_sec, 8) + 8 — tight so saturation "
                         "shows up fast instead of waiting out dead sessions)")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
