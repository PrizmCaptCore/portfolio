import json
import time


class Node:
    def __init__(self):
        self.uuid = None  # Node's uuid
        self.pre = []  # pre nodes uuid
        self.post = []  # post nodes uuid
        self.status = ["active", "inactive"]  # Node's status
        self.value = json.loads("{}")  # Json arch
        self.date = time.time()  # Signal's timestamp


# --- harness helpers around the canonical class (do not fork Node) ---
_seq = [0]


def new(value=None, kind="n"):
    """A canonical Node with a harness-assigned uuid + monotonic date (stream ordering)."""
    _seq[0] += 1
    n = Node()
    n.uuid = f"{kind}{_seq[0]}"
    n.value = value or {}
    n.date = _seq[0]
    return n


def to_dict(n):
    v = {
        k: x for k, x in n.value.items() if not k.startswith("_")
    }  # drop internal _fields
    return {"uuid": n.uuid, "pre": n.pre, "post": n.post, "value": v, "date": n.date}


def link(child, parent):
    if parent.uuid not in child.pre:
        child.pre.append(parent.uuid)
        parent.post.append(child.uuid)
