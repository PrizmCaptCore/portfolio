import os, re, json, requests

BACKEND = os.environ.get("BACKEND", "small")   # "small" (runpod gemma) | "claude"
WORKSPACE = ("An AI startup building a meeting-intelligence product "
             "(web platform + desktop assistant). Work = engineering, product, GTM, fundraising, ops.")
SYS = (
    f'You read the work chat of this team:\n  {WORKSPACE}\n'
    'Classify the LAST message RELATIVE TO THIS team\'s work.\n'
    'Default to "noise". Tag work ONLY if it concerns the team\'s work above:\n'
    '  decision = a real choice about the team\'s product/strategy/business\n'
    '  action   = a concrete work task (to do or done)\n'
    '  issue    = a work problem/blocker/risk\n'
    'Anything NOT about this team\'s work (greetings, meals, snacks, "let me in", '
    'small talk, arrivals/location, bare link/photo/file) = noise.\n'
    'JSON only: {"type":"...","title":"<=8 words"}'
)
CHAT    = os.environ.get("CHAT_LOG", "chat_log.txt")
START, END = 82, 106   # work-heavy slice: on-device -> SaaS decision episode (recall test)

def ask_small(user):
    return requests.post(os.environ.get("SMALL_LLM_URL", "http://localhost:8000/v1/chat/completions"),
        headers={"X-Internal-Key": os.environ["SMALL_KEY"]},
        json={"temperature": 0, "max_tokens": 128,
              "messages": [{"role": "system", "content": SYS},
                           {"role": "user", "content": user}]}
        ).json()["choices"][0]["message"]["content"]

def ask_claude(user):
    return requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
              "max_tokens": 128, "system": SYS,
              "messages": [{"role": "user", "content": user}]}
        ).json()["content"][0]["text"]

ASK = {"small": ask_small, "claude": ask_claude}[BACKEND]

def classify(history):                              # history = growing list, past-only
    user = "CHAT SO FAR:\n" + "\n".join(history[:-1]) + "\n\nLAST:\n" + history[-1]
    return json.loads(re.search(r"\{.*\}", ASK(user), re.S).group(0))

M    = re.compile(r"^\[([^\]]+)\] \[(?:오전|오후) ?\d+:\d+\] (.*)$")
msgs = [f"[{m[1]}] {m[2]}" for m in (M.match(l.rstrip()) for l in open(CHAT, encoding="utf-8")) if m]

OUT = {"small": "replay_out.json", "claude": "replay_claude.json"}[BACKEND]
out = []
for i in range(START, min(END, len(msgs))):
    r = classify(msgs[:i + 1])                       # growing context still from msg 0 (real prior)
    out.append({"i": i, "msg": msgs[i], **r})
    print(i, r.get("type"), msgs[i][:50])
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"-> {OUT}")
