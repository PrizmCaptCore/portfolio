"""conflict — a DIFF RANKER, not a contradiction judge.

Always surfaces the closest PRIOR decisions to a new one (topic-pruned, ranked) with their
diff. Topic overlap is a FLOOR (prune obviously-unrelated), not an auto-gate that hides things.
"""

from ..asker.llm import ask_json, toks


class Node_conflict:
    relation = ["reversal", "refinement", "unrelated"]
    SYS = (
        "A PRIOR decision and a NEW decision on a related topic. "
        "State their relation and what SPECIFICALLY changed.\n"
        'JSON only: {"rel":"reversal|refinement|unrelated","changed":"<short what differs>"}'
    )


def node_conflict(node, prior_decisions, k=5):
    """Diff ranker: topic-prune prior decisions, surface the closest k with their diff (ranked).
    Returns [{ref, rel, changed}, ...] — always proposes; the UI/threshold decides emphasis."""
    if node.value.get("type") != "decision":
        return []
    nt = toks(node.value.get("title"))
    cands = sorted(
        (p for p in prior_decisions if nt & toks(p.value.get("title"))),  # topic floor (no N²)
        key=lambda p: len(nt & toks(p.value.get("title"))),
        reverse=True,
    )[:k]
    diffs = []
    for p in cands:
        r = ask_json(
            Node_conflict.SYS,
            f"PRIOR: {p.value.get('title')}\nNEW: {node.value.get('title')}",
            {},
        )
        diffs.append({"ref": p.uuid, "rel": r.get("rel", "unrelated"), "changed": r.get("changed")})
    return diffs
