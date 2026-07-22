"""
회의 스트림 → 사건 그래프(event graph) 증분 빌더.

설계 원칙: LLM 은 '좁은 판단'만 하고, 그래프 '구조'는 결정론적 규칙이 정한다.
    node = node_structure(node)              # WHAT  -> node.value["type"] (+ title/actor/hints) 세팅
    node = node_grounding(node, activities)  # WHERE -> node.pre[] (belongs-to + caused-by) 세팅
    hits = node_conflict(node, decisions)    # vs 과거 -> 뒤집힌(reversal) 이전 decision 들

Node 스키마:  {uuid, pre[], post[], value{}, date}
  - LLM 호출은 분류/매칭 같은 좁은 판단에 한정
  - '새 activity 로 끊을지(the cut)' 는 규칙, LLM 추측이 아님
  - caused-by 엣지는 발화에 명시된 단서에서만 (환각 링크 방지)

* 이 파일은 포트폴리오용으로 sanitize 되었습니다: 내부 endpoint/키/제품 특정 내용 제거.
"""
import os
import re
import json
import requests

# ============================================================ LLM 클라이언트
# BACKEND=small  -> 사내 vLLM 서빙(소형 모델), BACKEND=frontier -> Claude
BACKEND = os.environ.get("BACKEND", "small")
SMALL_LLM_URL = os.environ.get("SMALL_LLM_URL", "http://localhost:8000/v1/chat/completions")


def ask(system, user, mt=300):
    if BACKEND == "small":
        r = requests.post(
            SMALL_LLM_URL,
            headers={"X-Internal-Key": os.environ.get("SMALL_LLM_KEY", "")},
            json={"temperature": 0, "max_tokens": mt,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
        )
        return r.json()["choices"][0]["message"]["content"]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
              "max_tokens": mt, "system": system,
              "messages": [{"role": "user", "content": user}]},
    )
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
        v = {k: x for k, x in self.value.items() if not k.startswith("_")}   # 내부 _필드 제거
        return {"uuid": self.uuid, "pre": self.pre, "post": self.post, "value": v, "date": self.date}


def link(child, parent):
    if parent.uuid not in child.pre:
        child.pre.append(parent.uuid)
        parent.post.append(child.uuid)


# ============================================================ 1. 구조화 (WHAT)
class Node_structure:
    type = ["decision", "action", "issue", "noise"]
    SYS = (
        "Classify the LAST message into decision | action | issue | noise (workspace-relative).\n"
        "Also extract: title(<=8w), actor, why_hint(stated cause via because/so/때문에 else null), "
        "ref_hint(refers back via that/그거/again else null).\n"
        'JSON only: {"type":"...","title":"...","actor":"...","why_hint":...,"ref_hint":...}')


def node_structure(node, context=""):
    """node.value['text'] (+context) 를 읽고 type/title/actor/why_hint/ref_hint 세팅."""
    r = ask_json(Node_structure.SYS,
                 f"CONTEXT:\n{context}\n\nMESSAGE:\n{node.value.get('text', '')}",
                 {"type": "noise"})
    node.value.update({k: r.get(k) for k in ("type", "title", "actor", "why_hint", "ref_hint")})
    return node


# ============================================================ 2. 접지 (WHERE)
class Node_grounding:
    role = ["initial", "stream", "terminal"]              # pre+subject 에서 파생, 직접 세팅 X
    MATCH = ("A new work item and a few OPEN activities. Which activity does it belong under "
             "(SAME specific matter), or none if it starts a new one. Match SPECIFIC matter, not loose topic.\n"
             'JSON only: {"id":"<activity uuid or null>"}')
    NAME = 'Give ONE short activity/workstream name (<=5 words). JSON only: {"name":"..."}'

    @staticmethod
    def surface(node, activities, k=5):
        """기계적 prune (임베딩 seam): 토큰 겹침 기준 top-k open activity (+최근)."""
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
        """LLM 매칭 신호: 어느 후보 activity 인지, 아니면 None."""
        if not candidates:
            return None
        listing = "\n".join(f"{c.uuid} | {c.value['title']}" for c in candidates)
        r = ask_json(Node_grounding.MATCH,
                     f"NEW ITEM: {node.value.get('title')}\n\nACTIVITIES:\n{listing}", {})
        return next((c for c in candidates if c.uuid == r.get("id")), None)

    @staticmethod
    def new_activity(node):
        name = ask_json(Node_grounding.NAME, node.value.get("title", ""), {}).get("name") or node.value.get("title")
        return Node({"type": "activity", "title": name, "_toks": toks(name), "_items": []}, kind="a")

    @staticmethod
    def causal(node, activity):
        """activity 내부 caused-by: 명시된 why/ref 단서에서만 (기계적, 추측 없음)."""
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
    """노드 배치: surface-prune -> LLM match -> cut-rule(none=>새 activity) + caused-by. node.pre[] 세팅."""
    act = Node_grounding.match(node, Node_grounding.surface(node, activities))   # LLM: 매칭 신호
    if act is None:                                                              # RULE: the cut
        act = Node_grounding.new_activity(node)
        activities.append(act)
    link(node, act)                                                              # belongs-to
    act.value["_toks"] |= toks(node.value.get("title"))
    parent = Node_grounding.causal(node, act)                                    # caused-by (명시된 것만)
    if parent:
        link(node, parent)
    act.value["_items"].append(node)
    return node


# ============================================================ 3. 충돌 (과거 decision 대비)
class Node_conflict:
    relation = ["reversal", "refinement", "none"]
    SYS = ("PRIOR decision vs a NEW decision. Is the NEW a REVERSAL of the prior "
           "(same subject, incompatible/opposite value)? refinement/compatible/unrelated = not reversal.\n"
           'JSON only: {"rel":"reversal|refinement|none"}')


def node_conflict(node, prior_decisions):
    """새 decision 노드를 과거 decision 들과 비교; 뒤집는(reverses) uuid 목록 반환."""
    if node.value.get("type") != "decision":
        return []
    hits = []
    for p in prior_decisions:
        r = ask_json(Node_conflict.SYS,
                     f"PRIOR: {p.value.get('title')}\nNEW: {node.value.get('title')}", {})
        if r.get("rel") == "reversal":
            hits.append(p.uuid)
    return hits


# ============================================================ compose (firehose 예시)
if __name__ == "__main__":
    # tree = []; 스트림의 각 message 마다: structure -> (noise 스킵) -> ground -> conflict -> append
    SAMPLES = [
        "이번 스프린트는 결제 모듈부터 붙이기로 하자.",
        "스테이징에서 웹훅이 간헐적으로 타임아웃 나요.",
        "웹훅 타임아웃 때문에 재시도 큐를 먼저 넣는 걸로 하자.",
        "아무래도 결제 모듈은 다음 스프린트로 미루자.",
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
        print(node.value.get("type"), "|", node.value.get("title"),
              "| pre", node.pre, "| conflicts", node.value["conflicts_with"])
