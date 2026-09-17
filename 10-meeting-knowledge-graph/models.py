"""
Modular model definitions.  Each model = a class (spec/vocab) + a function that ENRICHES a Node.

    node = node_structure(node)              # WHAT  -> sets node.value["type"] (+ title/actor/hints)
    node = node_grounding(node, activities)  # WHERE -> sets node.pre[]  (belongs-to + caused-by)
    hits = node_conflict(node, decisions)    # vs past -> reversed prior decisions

Node conforms to node_arch/node.py:  {uuid, pre[], post[], value{}, date}
LLM does only narrow judgments; the CUT (new activity) is a deterministic rule.
"""
import os, re, json, requests

# ============================================================ LLM client
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


# ============================================================ Node
_uid = [0]


class Node:
    def __init__(self, value=None, kind="n"):
        _uid[0] += 1
        self.uuid = f"{kind}{_uid[0]}"
        self.pre, self.post = [], []
        self.value = value or {}
        self.date = _uid[0]

    def to_dict(self):
        v = {k: x for k, x in self.value.items() if not k.startswith("_")}   # drop internal _fields
        return {"uuid": self.uuid, "pre": self.pre, "post": self.post, "value": v, "date": self.date}


def link(child, parent):
    if parent.uuid not in child.pre:
        child.pre.append(parent.uuid)
        parent.post.append(child.uuid)


# ============================================================ 1. structuring (WHAT)
class Node_structure:
    type = ["decision", "action", "issue", "noise"]
    SYS = (
        "Classify the LAST message into decision | action | issue | noise (workspace-relative).\n"
        "Also extract: title(<=8w), actor, why_hint(stated cause via because/so/때문에 else null), "
        "ref_hint(refers back via that/그거/again else null).\n"
        'JSON only: {"type":"...","title":"...","actor":"...","why_hint":...,"ref_hint":...}')


def node_structure(node, context=""):
    """Read node.value['text'] (+ context) -> set type/title/actor/why_hint/ref_hint. Returns node."""
    r = ask_json(Node_structure.SYS, f"CONTEXT:\n{context}\n\nMESSAGE:\n{node.value.get('text','')}",
                 {"type": "noise"})
    node.value.update({k: r.get(k) for k in ("type", "title", "actor", "why_hint", "ref_hint")})
    return node


# ============================================================ 2. grounding (WHERE)
class Node_grounding:
    role = ["initial", "stream", "terminal"]              # derived from pre+subject, not set directly
    MATCH = ("A new work item and a few OPEN activities. Which activity does it belong under "
             "(SAME specific matter), or none if it starts a new one. Match SPECIFIC matter, not loose topic.\n"
             'JSON only: {"id":"<activity uuid or null>"}')
    NAME = 'Give ONE short activity/workstream name (<=5 words). JSON only: {"name":"..."}'

    @staticmethod
    def surface(node, activities, k=5):
        """MECHANICAL prune (embedding seam): top-k open activities by token overlap (+ recent)."""
        nt = toks(node.value.get("title")) | toks(node.value.get("why_hint")) | toks(node.value.get("ref_hint"))
        top = sorted(activities, key=lambda a: len(nt & a.value["_toks"]), reverse=True)[:k]
        for a in reversed(activities):
            if len(top) >= k:
                break
            if a not in top:
                top.append(a)
        return top

    @staticmethod
    def match(node, candidates):
        """LLM match signal: which candidate activity, or None."""
        if not candidates:
            return None
        listing = "\n".join(f"{c.uuid} | {c.value['title']}" for c in candidates)
        r = ask_json(Node_grounding.MATCH, f"NEW ITEM: {node.value.get('title')}\n\nACTIVITIES:\n{listing}", {})
        return next((c for c in candidates if c.uuid == r.get("id")), None)

    @staticmethod
    def new_activity(node):
        name = ask_json(Node_grounding.NAME, node.value.get("title", ""), {}).get("name") or node.value.get("title")
        return Node({"type": "activity", "title": name, "_toks": toks(name), "_items": []}, kind="a")

    @staticmethod
    def causal(node, activity):
        """caused-by within the activity, ONLY from explicit why/ref hints (mechanical, no guessing)."""
        ht = toks((node.value.get("why_hint") or "") + " " + (node.value.get("ref_hint") or ""))
        if not ht:
            return None
        best, sc = None, 0
        for s in activity.value["_items"]:
            v = len(ht & toks(s.value.get("title")))
            if v > sc:
                best, sc = s, v
        return best if sc > 0 else None


def node_grounding(node, activities):
    """Place node: surface-prune -> LLM match -> cut-rule(none=>new) + caused-by. Sets node.pre[]."""
    act = Node_grounding.match(node, Node_grounding.surface(node, activities))   # LLM: match signal
    if act is None:                                                              # RULE: the cut
        act = Node_grounding.new_activity(node)
        activities.append(act)
    link(node, act)                                                              # belongs-to
    act.value["_toks"] |= toks(node.value.get("title"))
    parent = Node_grounding.causal(node, act)                                    # caused-by (explicit only)
    if parent:
        link(node, parent)
    act.value["_items"].append(node)
    return node


# ============================================================ 3. conflict (vs past decisions)
class Node_conflict:
    relation = ["reversal", "refinement", "none"]
    SYS = ("PRIOR decision vs a NEW decision. Is the NEW a REVERSAL of the prior "
           "(same subject, incompatible/opposite value)? refinement/compatible/unrelated = not reversal.\n"
           'JSON only: {"rel":"reversal|refinement|none"}')


def node_conflict(node, prior_decisions):
    """Compare a new decision node vs prior decisions; return uuids it reverses (conflicts_with)."""
    if node.value.get("type") != "decision":
        return []
    hits = []
    for p in prior_decisions:
        r = ask_json(Node_conflict.SYS, f"PRIOR: {p.value.get('title')}\nNEW: {node.value.get('title')}", {})
        if r.get("rel") == "reversal":
            hits.append(p.uuid)
    return hits


# ============================================================ compose (firehose example)
if __name__ == "__main__":
    # tree = []; for message in stream: structure -> (skip noise) -> ground -> conflict -> append
    SAMPLES = [
        "Let's switch the desktop assistant to a cloud SaaS model.",
        "MS Defender keeps blocking the .msi installer.",
        "Let's purchase DigiCert next week because Defender blocks the unsigned installer.",
        "Actually, let's stay on-device after all.",
    ]
    tree, activities = [], []
    for text in SAMPLES:
        node = node_structure(Node({"text": text}))
        if node.value.get("type") == "noise":
            continue
        node_grounding(node, activities)
        decisions = [n for n in tree if n.value.get("type") == "decision"]
        node.value["conflicts_with"] = node_conflict(node, decisions)
        tree.append(node)
        print(node.value.get("type"), "|", node.value.get("title"), "| pre", node.pre,
              "| conflicts", node.value["conflicts_with"])
