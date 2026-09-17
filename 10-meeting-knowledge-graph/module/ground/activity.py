"""activity — branch lifecycle: create a branch, and place a node under one (the linking)."""
from ..asker.llm import ask_json, toks
from ..node_arch.node import new, link

NAME = (
    "Give ONE short activity/workstream name (<=5 words) for these items — name it after the "
    "SPECIFIC subject/matter, NOT a meeting or ritual "
    '(never "daily sync", "standup", "weekly meeting", "1:1"). JSON only: {"name":"..."}'
)


def new_activity(titles):
    name = ask_json(NAME, " / ".join(t for t in titles if t), {}).get("name") or titles[0]
    return new({"type": "activity", "title": name, "_name_toks": toks(name), "_items": []}, kind="a")


def place_under(node, activity, parent=None):
    """belongs-to (activity) + optional caused-by (parent) + register as member.
    NOTE: we do NOT union the member's tokens into the activity — its surface stays bounded
    (name + recent members, see surface.node_toks) to avoid the rich-get-richer magnet."""
    link(node, activity)                          # belongs-to
    if parent is not None:
        link(node, parent)                        # caused-by
    activity.value["_items"].append(node)
    node.value["_act"] = activity                 # internal back-ref, for dependency routing
