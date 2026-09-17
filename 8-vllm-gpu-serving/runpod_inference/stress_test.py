"""
Stress test for the Inference (Gemma-4-E2B chat completions) service
via the production example.com gateway.

Login → access JWT → N concurrent POSTs to /ai/summarize/, released
together by an asyncio.Barrier. Per request we record HTTP status,
response parse outcome, and wall-clock latency. Successful responses
emit a content sample so a 200 OK with an empty body still shows up
as a failure in the breakdown.

Required env (.env in CWD or process env):
  ID, PW                          login credentials
  STT_GATEWAY_BASE (optional)     default https://api.example.com/api/v1

Usage:
  python stress_test.py --sessions 4
"""

import argparse
import asyncio
import os
import statistics
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv


DEFAULT_GATEWAY = "https://api.example.com/api/v1"
PATH = "/ai/summarize/"
# Realistic meeting-transcript style input. Short toy prompts under-test
# the service — vLLM batches small prompts trivially and we miss the
# memory / context-length pressure real production workload puts on it.
DEFAULT_TEXT_FILE = Path(__file__).with_name("stress_test_text.txt")


def _build_body(transcript: str, max_tokens: int) -> dict:
    return {
        "messages": [
            {"role": "system", "content":
                "You are a meeting assistant. Produce a concise summary "
                "and a bulleted list of decisions and action items."},
            {"role": "user", "content":
                "Summarize the following meeting transcript:\n\n" + transcript},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }


def _parse(data: dict) -> str:
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")[:120]


async def login(client: httpx.AsyncClient, base: str, email: str, password: str) -> str:
    r = await client.post(
        f"{base}/auth/token/",
        json={"email": email, "password": password},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["access"]


async def one_request(
    sid: int,
    client: httpx.AsyncClient,
    base: str,
    jwt: str,
    transcript: str,
    max_tokens: int,
    barrier: asyncio.Barrier,
    timeout_sec: float,
    results: dict,
) -> None:
    err: Optional[str] = None
    status: Optional[int] = None
    sample: str = ""
    t_send: Optional[float] = None
    t_recv: Optional[float] = None
    await barrier.wait()
    try:
        t_send = time.monotonic()
        resp = await client.post(
            f"{base}{PATH}",
            headers={"Authorization": f"Bearer {jwt}"},
            json=_build_body(transcript, max_tokens),
            timeout=timeout_sec,
        )
        t_recv = time.monotonic()
        status = resp.status_code
        if resp.status_code >= 400:
            err = f"http {resp.status_code}: {resp.text[:200]}"
        else:
            try:
                data = resp.json()
                sample = _parse(data) or ""
                if not sample:
                    err = "empty content in response"
            except Exception as e:
                err = f"json parse: {type(e).__name__}: {e}"
    except httpx.TimeoutException:
        err = f"timeout after {timeout_sec:.0f}s"
        t_recv = time.monotonic()
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        t_recv = time.monotonic()

    latency_ms = None
    if t_send is not None and t_recv is not None:
        latency_ms = (t_recv - t_send) * 1000

    results[sid] = {
        "status": status,
        "err": err,
        "sample": sample,
        "latency_ms": latency_ms,
    }


async def main_async(args):
    load_dotenv()
    email = args.email or os.environ.get("ID")
    password = args.password or os.environ.get("PW")
    if not (email and password):
        raise SystemExit("ID/PW not set (use --email/--password or env via .env)")
    base = args.gateway or os.environ.get("STT_GATEWAY_BASE", DEFAULT_GATEWAY)

    text_path = Path(args.text_file) if args.text_file else DEFAULT_TEXT_FILE
    if not text_path.exists():
        raise SystemExit(f"text file not found: {text_path}")
    transcript = text_path.read_text(encoding="utf-8")
    print(
        f"Transcript loaded: {text_path}  "
        f"({len(transcript)} chars, ~{len(transcript.split())} words)",
        flush=True,
    )

    async with httpx.AsyncClient(verify=True) as http:
        t0 = time.monotonic()
        print(f"Login {email} → {base}/auth/token/", flush=True)
        jwt = await login(http, base, email, password)
        print(f"  jwt acquired ({(time.monotonic() - t0) * 1000:.0f}ms)", flush=True)

        print(f"Service: inference  path: {PATH}  timeout: {args.timeout:.0f}s",
              flush=True)
        print(f"Opening {args.sessions} concurrent requests", flush=True)

        barrier = asyncio.Barrier(args.sessions)
        results: dict = {}
        await asyncio.gather(
            *(
                one_request(
                    i, http, base, jwt, transcript, args.max_tokens,
                    barrier, args.timeout, results,
                )
                for i in range(args.sessions)
            )
        )

    ok = 0
    bad = 0
    latencies: list[float] = []
    err_counts: dict[str, int] = {}
    for sid in sorted(results):
        r = results[sid]
        lat = r.get("latency_ms")
        if r.get("err"):
            bad += 1
            key = r["err"][:80]
            err_counts[key] = err_counts.get(key, 0) + 1
            print(
                f"  s{sid:03d}: ERR  {('%.0fms' % lat) if lat else 'n/a'}  "
                f"{r['err']}",
                flush=True,
            )
        else:
            ok += 1
            if lat is not None:
                latencies.append(lat)
            print(
                f"  s{sid:03d}: OK   {('%.0fms' % lat) if lat else 'n/a'}  "
                f"sample={r['sample']!r}",
                flush=True,
            )

    print()
    print("== summary ==")
    print(f"  service   : inference")
    print(f"  requests  : {args.sessions}")
    print(f"  ok        : {ok}")
    print(f"  errors    : {bad}")
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = (
            latencies[int(len(latencies) * 0.95)]
            if len(latencies) >= 20 else max(latencies)
        )
        print(
            f"  latency   : p50={p50:.0f}ms  p95={p95:.0f}ms  max={max(latencies):.0f}ms"
        )
    if err_counts:
        print("  error breakdown:")
        for k, v in sorted(err_counts.items(), key=lambda x: -x[1]):
            print(f"    [{v}x] {k}")
    if bad > 0:
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--email", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--gateway", default="",
                    help=f"Override gateway base (default {DEFAULT_GATEWAY})")
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="Per-request timeout in seconds (default 120)")
    ap.add_argument("--text-file", default="",
                    help=f"Transcript path (default {DEFAULT_TEXT_FILE.name} "
                         "next to this script)")
    ap.add_argument("--max-tokens", type=int, default=300,
                    help="Max tokens to generate per response (default 300)")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
