"""surface — pick which candidates to even consider (cheap signal). Embedding seam.

Token overlap now; swap `node_toks`/`select_candidates` for an embedding index later
without touching match / dependency / orchestration.
"""
from ..asker.llm import toks

RECENT_EVIDENCE = 3   # an activity is represented by its NAME + only its few most recent members


def node_toks(n):
    """Tokens for surface matching.
    Activity = its NAME + most RECENT members only (BOUNDED — no rich-get-richer union, so a big
    activity does not become a token magnet). A loose item = its title + hints."""
    if n.value.get("type") == "activity":
        t = set(n.value.get("_name_toks", set()))
        for it in n.value.get("_items", [])[-RECENT_EVIDENCE:]:
            t |= toks(it.value.get("title"))
        return t
    return toks(n.value.get("title")) | toks(n.value.get("why_hint")) | toks(n.value.get("ref_hint"))


def select_candidates(node, candidates, k=5):
    """Top-k candidates that ACTUALLY share signal (overlap > 0). No zero-overlap fallback:
    an unrelated item must get NO candidate, so match returns None and it parks/births instead of
    being funnelled into whatever activity happens to exist (the single-sink over-merge)."""
    nt = node_toks(node)
    scored = [(len(nt & node_toks(c)), c) for c in candidates]
    return [c for s, c in sorted(scored, key=lambda x: x[0], reverse=True) if s > 0][:k]
