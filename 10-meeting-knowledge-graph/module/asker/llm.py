"""LLM client — small (runpod gemma) | claude (anthropic). Plus tiny helpers."""
import os, re, json, requests

BACKEND = os.environ.get("BACKEND", "small")
RUNPOD  = os.environ.get("SMALL_LLM_URL", "http://localhost:8000/v1/chat/completions")


def ask(system, user, mt=300):
    if BACKEND == "small":
        r = requests.post(RUNPOD, headers={"X-Internal-Key": os.environ["SMALL_KEY"]},
                          json={"temperature": 0, "max_tokens": mt,
                                "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": user}]})
        return r.json()["choices"][0]["message"]["content"]
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                               "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                            "max_tokens": mt, "system": system, "messages": [{"role": "user", "content": user}]})
    return r.json()["content"][0]["text"]


def ask_json(system, user, default):
    try:
        return json.loads(re.search(r"(\{.*\}|\[.*\])", ask(system, user), re.S).group(0))
    except Exception:
        return default


def toks(s):
    return set(re.findall(r"[a-z가-힣0-9]+", (s or "").lower()))
