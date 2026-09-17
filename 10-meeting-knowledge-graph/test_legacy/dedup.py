import os, re, json, requests

BACKEND = os.environ.get("BACKEND", "small")   # "small" | "claude"
CHAT    = os.environ.get("CHAT_LOG", "chat_log.txt")
START, END = 82, 106
SYS = (
    'You dedup a team decision discussion. You get DECISIONS SO FAR (id | variable | value) '
    'and the LATEST message.\n'
    'Extract the LATEST (variable, value), then relate to the list:\n'
    '  restates/refines an existing one  -> {"rel":"merge","id":<id>}\n'
    '  reverses one (same variable, incompatible value) -> {"rel":"reversal","id":<id>}\n'
    '  a NEW decision -> {"rel":"new"}\n'
    '  not a decision (chatter/rationale/agreement/photo) -> {"rel":"none"}\n'
    'JSON only: {"variable":"...","value":"...","rel":"...","id":<id or null>}'
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

decisions, log = [], []
for i in range(START, min(END, len(msgs))):
    lst = "\n".join(f'{d["id"]} | {d["variable"]} | {d["value"]}' for d in decisions) or "(none)"
    r = json.loads(re.search(r"\{.*\}", ASK(f"DECISIONS SO FAR:\n{lst}\n\nLATEST:\n{msgs[i]}"), re.S).group(0))
    rel = r.get("rel")
    if rel == "new":
        decisions.append({"id": f"D{len(decisions)+1}", "variable": r.get("variable"),
                          "value": r.get("value"), "turns": [i]})
    elif rel in ("merge", "reversal"):
        for d in decisions:
            if d["id"] == r.get("id"):
                d["turns"].append(i)
                if rel == "reversal":
                    d["value"] = r.get("value")
                break
    log.append({"i": i, "rel": rel, "id": r.get("id"), "msg": msgs[i][:50]})
    print(f'{i:3} {str(rel):8} {str(r.get("id") or ""):4} {msgs[i][:46]}')

print("\n=== distinct decisions ===")
for d in decisions:
    print(f'{d["id"]} | {d["variable"]} | {d["value"]} | turns {d["turns"]}')
json.dump({"decisions": decisions, "log": log},
          open(f"dedup_{BACKEND}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n-> dedup_{BACKEND}.json")
