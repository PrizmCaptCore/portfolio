"""grounding (WHERE) — ORCHESTRATION ONLY. Routes a node to EXTEND / BIRTH / PARK.

Stages (each its own module):
  surface.select_candidates   who to even consider        (mechanical, embedding seam)
  match.match_activity        belongs-to judgment         (the only LLM call)
  dependency.find_parent      caused-by resolution        (BEFORE placement, a connection channel)
  activity.new_activity/place_under   branch lifecycle + linking

Policy (can_place): a node is placed if it CONNECTS — either it belongs-to a branch / parked
peer, OR its explicit reference resolves to a prior node. Otherwise it PARKS.
A lone item never seeds a branch; a branch is born only from a connection.
"""
from .surface import select_candidates, node_toks
from .match import match_activity
from .dependency import find_parent
from .activity import new_activity, place_under


def _placed_items(activities):
    return [it for a in activities for it in a.value["_items"]]


def node_grounding(node, activities, pending):
    """Returns the list of nodes newly placed (the caller commits them); [] if parked."""
    target = match_activity(node, select_candidates(node, activities + pending))  # belongs-to (LLM)
    parent = find_parent(node, _placed_items(activities))                         # caused-by (BEFORE placement)

    # POLICY HOOK: to make a missing referent BLOCK placement, park here when
    # dependency.has_reference(node) and parent is None. Default policy is softer (below).

    if target is not None and target.value.get("type") == "activity":            # EXTEND existing branch
        place_under(node, target, parent)
        return [node]
    if target is not None:                                                       # BIRTH from a parked peer
        act = new_activity([target.value.get("title"), node.value.get("title")])
        activities.append(act)
        pending.remove(target)
        place_under(target, act)
        place_under(node, act, parent)
        return [target, node]
    if parent is not None:                                                       # connect via caused-by alone
        place_under(node, parent.value["_act"], parent)
        return [node]
    pending.append(node)                                                         # PARK — no connection
    return []


def reclaim(activities, pending):
    """Attach parked items that now connect to an EXISTING branch (never births). Returns attached nodes."""
    attached, still = [], []
    for nd in pending:
        if not any(node_toks(nd) & node_toks(a) for a in activities):            # surface gate
            still.append(nd)
            continue
        target = match_activity(nd, select_candidates(nd, activities))           # activities only -> no birth
        parent = find_parent(nd, _placed_items(activities))
        if target is not None and target.value.get("type") == "activity":
            place_under(nd, target, parent)
            attached.append(nd)
        elif parent is not None:
            place_under(nd, parent.value["_act"], parent)
            attached.append(nd)
        else:
            still.append(nd)
    pending[:] = still
    return attached
