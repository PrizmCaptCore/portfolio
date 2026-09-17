"""
Firehose pipeline — single streaming pass (thin driver over the modular models).

    tree = []
    for message in time-ordered stream:
        node = node_structure(node)         # WHAT  (once, on arrival)
        if noise: skip
        node_grounding(node, activities)    # WHERE (incremental: surface-prune + cut-rule)
        node_conflict(node, decisions)      # vs past decisions
        tree.append(node)

No batch, no N² over all items, no re-extraction.
"""
import json
from .asker.llm import BACKEND
from .node_arch.node import new, to_dict
from .struct.pipeline import node_structure
from .ground.grounding import node_grounding, reclaim
from .conflict.conflict import node_conflict
from .tester_stream.stream import parse_stream


def run_firehose(d0=(4, 15), d1=(5, 9), out=None):
    stream = parse_stream(d0, d1)
    tree, activities, pending = [], [], []

    def commit(node):
        # diff ranker vs past decisions (topic-pruned inside node_conflict)
        node.value["diffs"] = node_conflict(node, [x for x in tree if x.value.get("type") == "decision"])
        tree.append(node)

    for i, (day, line) in enumerate(stream):
        node = new({"text": line, "day": f"{day[0]}/{day[1]}"})
        node_structure(node)                                             # WHAT (once, per message)
        if node.value.get("type") in (None, "noise"):
            continue                                                     # bucket: drop
        placed = node_grounding(node, activities, pending)               # WHERE: extend / birth / park
        for nd in placed:                                                # [] if parked
            commit(nd)
        if placed:                                                       # frontier changed -> re-examine pending
            for nd in reclaim(activities, pending):
                commit(nd)
        print(f"  streamed {i+1}/{len(stream)}  acts={len(activities)} placed={len(tree)} pending={len(pending)}",
              end="\r")
    print()
    for nd in reclaim(activities, pending):                              # final sweep
        commit(nd)

    out = out or f"frontier_{BACKEND}.json"
    json.dump({"nodes": [to_dict(a) for a in activities] + [to_dict(t) for t in tree],
               "pending": [to_dict(p) for p in pending]},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{len(activities)} activities / {len(tree)} placed / {len(pending)} pending -> {out}")
    for a in activities:
        print(f'  {a.uuid} | {a.value["title"]} | {len(a.value["_items"])} items')
    return activities, tree, pending
