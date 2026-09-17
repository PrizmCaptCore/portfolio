import os, re, json, requests

BACKEND = os.environ.get("BACKEND", "small")   # "small" | "claude"
CHAT    = os.environ.get("CHAT_LOG", "chat_log.txt")
START, END = 344, 418
SYS = (
    'You track PARALLEL work threads in a QA/bug chat. You get THREADS SO FAR (id | topic | last msg) '
    'and the LATEST message.\n'
    'Decide: does LATEST CONTINUE one of them, START a new thread, or none (chatter/ack/photo/emoji)?\n'
    'KEY RULE: similar topics can be DIFFERENT threads. "summary slow", "install/download fails", '
    '"autoscroller", "server down" are SEPARATE threads even though all are bugs. '
    'Match the SPECIFIC issue, not just "a bug".\n'
    'JSON only: {"topic":"<short>","rel":"continue|new|none","id":<thread id or null>}'
)

def ask_small(u):
    return requests.post(os.environ.get("SMALL_LLM_URL", "http://localhost:8000/v1/chat/completions"),
        headers={"X-Internal-Key": os.environ["SMALL_KEY"]},
        json={"temperature": 0, "max_tokens": 128,
              "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": u}]}
        ).json()["choices"][0]["message"]["content"]

def ask_claude(u):
    return requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
              "max_tokens": 128, "system": SYS, "messages": [{"role": "user", "content": u}]}
        ).json()["content"][0]["text"]

ASK = {"small": ask_small, "claude": ask_claude}[BACKEND]

M    = re.compile(r"^\[([^\]]+)\] \[(?:오전|오후) ?\d+:\d+\] (.*)$")
msgs = [f"[{m[1]}] {m[2]}" for m in (M.match(l.rstrip()) for l in open(CHAT, encoding="utf-8")) if m]

threads, log = [], []
for i in range(START, min(END, len(msgs))):
    lst = "\n".join(f'{t["id"]} | {t["topic"]} | {t["last"]}' for t in threads) or "(none)"
    r = json.loads(re.search(r"\{.*\}", ASK(f"THREADS SO FAR:\n{lst}\n\nLATEST:\n{msgs[i]}"), re.S).group(0))
    rel = r.get("rel")
    if rel == "new":
        threads.append({"id": f"T{len(threads)+1}", "topic": r.get("topic"), "last": msgs[i][:40], "turns": [i]})
    elif rel == "continue":
        for t in threads:
            if t["id"] == r.get("id"):
                t["turns"].append(i); t["last"] = msgs[i][:40]; break
    log.append({"i": i, "rel": rel, "id": r.get("id"), "topic": r.get("topic"), "msg": msgs[i][:50]})
    print(f'{i:3} {str(rel):8} {str(r.get("id") or ""):4} {str(r.get("topic",""))[:16]:16} {msgs[i][:38]}')

print("\n=== threads ===")
for t in threads:
    print(f'{t["id"]} | {t["topic"]} | turns {t["turns"]}')
json.dump({"threads": threads, "log": log},
          open(f"thread_{BACKEND}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n-> thread_{BACKEND}.json")
