"""
Firehose grounding — streaming, single pass, persisted growing tree.

    tree = []
    for message in time-ordered stream:
        node = structuring(message)     # once, on arrival
        if noise: skip
        ground(node, open_activities)   # surface-prune candidates + cut-rule (deterministic)
        tree.append(node)

No batch, no N², no re-extraction. Each message is consumed exactly once, in order.
(structuring runs on a small sliding window since a single line is often a fragment.)
Nodes conform to node_arch/node.py: {uuid, pre[], post[], value{}, date}.
"""
import os, re, json, requests

# ============================== config / LLM client ==============================
BACKEND   = os.environ.get("BACKEND", "small")
WORKSPACE = "An AI startup building a meeting-intelligence product."
RUNPOD    = os.environ.get("SMALL_LLM_URL", "http://localhost:8000/v1/chat/completions")
CHAT      = os.environ.get("CHAT_LOG", "chat_log.txt")
WIN       = 6        # messages per structuring window (streaming; each message consumed once)


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


def parse_json(raw, default):
    try:
        return json.loads(re.search(r"(\{.*\}|\[.*\])", raw, re.S).group(0))
    except Exception:
        return default


def toks(s):
    return set(re.findall(r"[a-z가-힣0-9]+", (s or "").lower()))


# ============================== Node ==============================
_uid = [0]


def make_node(value, kind="n"):
    _uid[0] += 1
    return {"uuid": f"{kind}{_uid[0]}", "pre": [], "post": [], "value": value, "date": _uid[0]}


def attach(child, parent):
    if parent["uuid"] not in child["pre"]:
        child["pre"].append(parent["uuid"])
        parent["post"].append(child["uuid"])


# ============================== stream ==============================
def parse_stream(d0=(4, 15), d1=(5, 9)):
    """Flat, time-ordered list of (day_tuple, '[actor] text') within [d0, d1]."""
    DATE = re.compile(r'^-+\s*\d{4}년\s*(\d{1,2})월\s*(\d{1,2})일')
    MSG  = re.compile(r'^\[([^\]]+)\] \[(?:오전|오후) ?\d+:\d+\] (.*)$')
    SYSL = re.compile(r'(님이.*초대|방장이 되어|삭제되었습니다|님이 (나갔|들어왔))')
    out, cur = [], None
    for ln in open(CHAT, encoding="utf-8"):
        ln = ln.rstrip("\n")
        m = DATE.match(ln)
        if m:
            cur = (int(m[1]), int(m[2])); continue
        if SYSL.search(ln):
            continue
        mm = MSG.match(ln)
        if mm and cur and d0 <= cur <= d1:
            out.append((cur, f"[{mm[1]}] {mm[2]}"))
    return out


# ============================== structuring (once per window) ==============================
STRUCT_SYS = (
    f"Team: {WORKSPACE}\nExtract WORK items from this chat window. DROP chatter/greetings/meals/logistics/links/photos.\n"
    'Each item: {"type":"decision|action|issue","title":"<=8 words","actor":"<who>",'
    '"why_hint":"<stated cause via because/so/때문에, else null>",'
    '"ref_hint":"<what it refers back to via that/그거/again, else null>"}.\n'
    "Hints ONLY when explicitly in the text; else null. JSON array only; [] if none.")


def structuring(window_lines):
    arr = parse_json(ask(STRUCT_SYS, "\n".join(window_lines), 1200), [])
    return [it for it in arr if isinstance(it, dict) and it.get("type") in ("decision", "action", "issue")]


# ============================== grounding: surface-prune + cut-rule ==============================
def surface_candidates(node, activities, k=5):
    """MECHANICAL prune (seam for embedding later): top-k open activities by token overlap (+ recent)."""
    nt = toks(node["value"].get("title")) | toks(node["value"].get("why_hint")) | toks(node["value"].get("ref_hint"))
    ranked = sorted(activities, key=lambda a: len(nt & a["_toks"]), reverse=True)
    top = ranked[:k]
    for a in reversed(activities):
        if len(top) >= k:
            break
        if a not in top:
            top.append(a)
    return top


PICK_SYS = (
    "A new work item, and a few candidate OPEN activities. Which activity does it belong under "
    "(SAME specific matter), or none if it starts a new one.\n"
    "Match the SPECIFIC matter, not loose topic similarity.\n"
    'JSON only: {"id":"<activity uuid or null>"}')


def pick(node, candidates):
    """TINY bounded LLM match: which candidate activity (or None => new)."""
    if not candidates:
        return None
    listing = "\n".join(f'{c["uuid"]} | {c["value"]["title"]}' for c in candidates)
    r = parse_json(ask(PICK_SYS, f'NEW ITEM: {node["value"]["title"]}\n\nACTIVITIES:\n{listing}'), {})
    return next((c for c in candidates if c["uuid"] == r.get("id")), None)


NAME_SYS = ('Give ONE short activity/workstream name (<=5 words) for this work item. JSON only: {"name":"..."}')


def new_activity(node):
    name = parse_json(ask(NAME_SYS, node["value"].get("title", "")), {}).get("name") or node["value"].get("title")
    a = make_node({"type": "activity", "title": name}, "a")
    a["_toks"], a["_items"] = toks(name), []
    return a


def resolve_causal(node, siblings):
    """caused-by within the activity, ONLY from explicit why/ref hints (mechanical, no guessing)."""
    hint = (node["value"].get("why_hint") or "") + " " + (node["value"].get("ref_hint") or "")
    if not hint.strip():
        return None
    ht = toks(hint)
    best, sc = None, 0
    for s in siblings:
        v = len(ht & toks(s["value"].get("title")))
        if v > sc:
            best, sc = s, v
    return best if sc > 0 else None


def ground(node, activities):
    """Place ONE node incrementally: surface-prune -> LLM match -> cut-rule (attach known / open new)."""
    chosen = pick(node, surface_candidates(node, activities))      # LLM: match signal
    if chosen is None:                                             # cut-rule: none -> new activity
        chosen = new_activity(node)
        activities.append(chosen)
    attach(node, chosen)                                          # belongs-to
    chosen["_toks"] |= toks(node["value"].get("title"))           # grow activity surface
    parent = resolve_causal(node, chosen["_items"])               # caused-by (explicit hints, within activity)
    if parent:
        attach(node, parent)
    chosen["_items"].append(node)
    return chosen


# ============================== conflict ==============================
CONF_SYS = ("Among these DECISIONS find pairs that CONFLICT (same subject, incompatible/reversed value). "
            "Topic-similar but compatible = NOT a conflict.\n"
            'JSON: {"conflicts":[{"a":"uuid","b":"uuid","why":"<short>"}]}')


def conflict(decisions):
    if len(decisions) < 2:
        return []
    listing = "\n".join(f'{n["uuid"]} | {n["value"].get("title")}' for n in decisions)
    return parse_json(ask(CONF_SYS, listing, 800), {}).get("conflicts", [])


# ============================== firehose loop ==============================
def run():
    stream = parse_stream()
    tree, activities, buf = [], [], []
    for i, (day, line) in enumerate(stream):
        buf.append((day, line))
        if len(buf) >= WIN or i == len(stream) - 1:
            for it in structuring([ln for _, ln in buf]):           # structure window ONCE
                node = make_node({k: it.get(k) for k in ("type", "title", "actor", "why_hint", "ref_hint")})
                node["value"]["day"] = f"{buf[-1][0][0]}/{buf[-1][0][1]}"
                ground(node, activities)                            # place incrementally
                tree.append(node)
            buf = []
        print(f"  streamed {i+1}/{len(stream)}  acts={len(activities)}", end="\r")
    print()

    decisions = [n for n in tree if n["value"].get("type") == "decision"]
    conflicts = conflict(decisions)

    print(f"\n{len(activities)} activities / {len(tree)} items / {len(conflicts)} conflicts")
    for a in activities:
        print(f'  {a["uuid"]} | {a["value"]["title"]} | {len(a["_items"])} items')
    for a in activities:                                            # strip internal fields before save
        a.pop("_toks", None); a.pop("_items", None)
    json.dump({"nodes": activities + tree, "conflicts": conflicts},
              open(f"frontier_{BACKEND}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"-> frontier_{BACKEND}.json")


if __name__ == "__main__":
    run()
