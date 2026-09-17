from ..asker.llm import ask_json


class Node_structure:
    type = ["decision", "action", "issue", "noise"]
    SYS = (
        "Classify the MESSAGE into decision | action | issue | noise (workspace-relative; "
        "greetings/meals/logistics/links/photos/small-talk = noise).\n"
        "Also extract: title(<=8 words), actor, "
        "why_hint(stated cause via because/so/때문에, else null), "
        "ref_hint(refers back via that/그거/again, else null).\n"
        'JSON only: {"type":"...","title":"...","actor":"...","why_hint":...,"ref_hint":...}'
    )


def node_structure(node):
    """node.value['text'] -> set type/title/actor/why_hint/ref_hint. Returns node.
    Per-message classification; reference RESOLUTION is grounding's job (caused-by vs frontier)."""
    r = ask_json(Node_structure.SYS, node.value.get("text", ""), {"type": "noise"})
    node.value.update(
        {k: r.get(k) for k in ("type", "title", "actor", "why_hint", "ref_hint")}
    )
    return node
