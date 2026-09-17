import os, re, json, requests

BACKEND   = os.environ.get("BACKEND", "small")   # "small" | "claude"
CHAT      = os.environ.get("CHAT_LOG", "chat_log.txt")
START, END = 344, 418
WORKSPACE = ("An AI startup building a meeting-intelligence product "
             "(web platform + desktop assistant).")
# GENERIC grounding prompt: only the (inferred) workspace purpose. NO session framing,
# NO example identities. The model must DISCOVER the structure unaided.
SYS = (
    f"You track this team's work chat as a tree of nodes. Team: {WORKSPACE}\n"
    "You get the OPEN NODES so far (id | type | what) and the LATEST message.\n"
    "Output type = decision | action | issue | noise.\n"
    "If it is work, place it: does it CONTINUE an open node (which id?), is it NEW, or none(noise)?\n"
    "Match by the SPECIFIC matter discussed, NOT loose topic similarity — two different problems are "
    "different nodes even if both are bugs or both recent.\n"
    'JSON only: {"type":"...","what":"<short, for work>","rel":"continue|new|none","id":<node id or null>}'
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

nodes, log = [], []
for i in range(START, min(END, len(msgs))):
    lst = "\n".join(f'{n["id"]} | {n["type"]} | {n["what"]}' for n in nodes) or "(none)"
    raw = ASK(f"OPEN NODES:\n{lst}\n\nLATEST:\n{msgs[i]}")
    try:
        mm = re.search(r"\{.*?\}", raw, re.S)          # non-greedy: first {...} object
        r = json.loads(mm.group(0)) if mm else {"type": "?", "rel": "none"}
    except Exception:
        r = {"type": "?", "rel": "none", "raw": raw[:80]}
    if r.get("type") in ("decision", "action", "issue"):
        if r.get("rel") == "new":
            nodes.append({"id": f"N{len(nodes)+1}", "type": r.get("type"),
                          "what": r.get("what"), "turns": [i]})
        elif r.get("rel") == "continue":
            for n in nodes:
                if n["id"] == r.get("id"):
                    n["turns"].append(i); break
    log.append({"i": i, "type": r.get("type"), "what": r.get("what"),
                "rel": r.get("rel"), "id": r.get("id"), "msg": msgs[i][:46]})
    print(f'{i:3} {str(r.get("type")):8} {str(r.get("rel") or ""):8} {str(r.get("id") or ""):3} '
          f'{str(r.get("what") or "")[:18]:18} {msgs[i][:30]}')

print("\n=== nodes ===")
for n in nodes:
    print(f'{n["id"]} | {n["type"]} | {n["what"]} | turns {n["turns"]}')
json.dump({"nodes": nodes, "log": log},
          open(f"ground_{BACKEND}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n-> ground_{BACKEND}.json")
