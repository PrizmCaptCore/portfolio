"""match — the ONLY LLM judgment in grounding: which candidate shares the same matter (or none)."""
from ..asker.llm import ask_json

SYS = (
    "A NEW work item and a few CANDIDATES (open activities, or earlier loose items). "
    "Which ONE candidate shares the SAME specific matter (so they belong together), "
    "or null if none / you cannot confidently tell.\n"
    "Match the SPECIFIC matter (a workstream) — NOT a shared meeting/ritual context: "
    "both merely coming up in a daily sync / standup / weekly meeting is NOT a match. "
    "If the only thing in common is a meeting/session, answer null.\n"
    "Prefer null over guessing.\n"
    'JSON only: {"id":"<candidate uuid or null>"}'
)


def match_activity(node, candidates):
    """Return the candidate node it belongs with, or None."""
    if not candidates:
        return None
    listing = "\n".join(f"{c.uuid} | {c.value.get('title')}" for c in candidates)
    r = ask_json(SYS, f"NEW ITEM: {node.value.get('title')}\n\nCANDIDATES:\n{listing}", {})
    return next((c for c in candidates if c.uuid == r.get("id")), None)
