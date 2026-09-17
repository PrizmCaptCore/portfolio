"""dependency (caused-by) — resolve an item's EXPLICIT ref/why hint to a preceding node.

This is a CONNECTION channel evaluated BEFORE placement (not an after-the-fact optional link):
an item whose explicit reference resolves connects via that parent's branch. Mechanical,
explicit-hints-only (no guessing) — matches "null pre > wrong pre".
"""
from ..asker.llm import toks


def has_reference(node):
    """Does the item explicitly point back at something? (why/ref hint present)"""
    return bool(((node.value.get("why_hint") or "") + (node.value.get("ref_hint") or "")).strip())


def find_parent(node, prior_nodes):
    """Resolve the explicit why/ref hint to the best-matching prior node. None if it does not resolve."""
    ht = toks((node.value.get("why_hint") or "") + " " + (node.value.get("ref_hint") or ""))
    if not ht:
        return None
    best, sc = None, 0
    for p in prior_nodes:
        v = len(ht & toks(p.value.get("title")))
        if v > sc:
            best, sc = p, v
    return best if sc > 0 else None
