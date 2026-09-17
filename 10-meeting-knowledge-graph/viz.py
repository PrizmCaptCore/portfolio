import os, json, sys

BACKEND = os.environ.get("BACKEND", "small")
src = sys.argv[1] if len(sys.argv) > 1 else f"frontier_{BACKEND}.json"
data = json.load(open(src, encoding="utf-8"))
nodes = data["nodes"]
pending = data.get("pending", [])
byid = {n["uuid"]: n for n in nodes}
actset = {n["uuid"] for n in nodes if n["value"].get("type") == "activity"}
act_ids = [n["uuid"] for n in nodes if n["value"].get("type") == "activity"]


def belongs_to(n):                              # the activity a node hangs under (its activity-pre)
    return next((p for p in n.get("pre", []) if p in actset), None)


# --- TIME is the backbone: x = chronological rank (by date); y = activity lane ---
timeline = sorted([n for n in nodes if n["value"].get("type") != "activity"] + pending, key=lambda n: n["date"])
xrank = {n["uuid"]: i for i, n in enumerate(timeline)}
XS, YS = 55, 120
lane = {a: i for i, a in enumerate(act_ids)}
PENDING_LANE = len(act_ids)

PAL = ["#4e79a7", "#59a14f", "#e15759", "#f28e2b", "#76b7b2", "#edc948", "#b07aa1", "#9c755f", "#ff9da7", "#bab0ac"]
acol = {a: PAL[k % len(PAL)] for k, a in enumerate(act_ids)}
SHAPE = {"decision": "dot", "action": "square", "issue": "triangle"}


def xpos(uid):
    return xrank.get(uid, 0) * XS


vn, ve = [], []
for n in nodes:                                 # activity hubs: at the LEFT edge of their time-span, on their lane
    if n["value"].get("type") != "activity":
        continue
    uid = n["uuid"]
    xs = [xpos(it["uuid"]) for it in nodes if belongs_to(it) == uid]
    vn.append({"id": uid, "label": n["value"].get("title", ""), "shape": "box",
               "x": (min(xs) - XS) if xs else 0, "y": lane[uid] * YS, "fixed": True,
               "color": {"background": "#ffffff", "border": acol.get(uid, "#999")}, "borderWidth": 2,
               "font": {"size": 16, "color": acol.get(uid, "#333")}})

for n in nodes:                                 # items: x = time, y = activity lane
    t, uid = n["value"].get("type"), n["uuid"]
    if t == "activity":
        continue
    a = belongs_to(n)
    vn.append({"id": uid, "label": n["value"].get("title", ""), "shape": SHAPE.get(t, "dot"),
               "x": xpos(uid), "y": lane.get(a, PENDING_LANE) * YS, "fixed": True,
               "color": {"background": "#ffffff", "border": acol.get(a, "#bbb")},
               "title": f'{t} · {n["value"].get("actor","")} · {n["value"].get("day","")}'})
    if a:                                        # belongs-to: faint, no arrow
        ve.append({"from": a, "to": uid, "width": 1, "color": {"color": acol.get(a, "#ccc"), "opacity": 0.3}})
    for p in n.get("pre", []):                   # caused-by: item -> item, dashed arrow (reads left->right in time)
        if p in byid and p not in actset:
            ve.append({"from": p, "to": uid, "arrows": "to", "dashes": True, "width": 1.5,
                       "color": {"color": "#666"}})
    for d in n["value"].get("diffs", []):        # diff ranker: red dashed, labelled by relation
        if d.get("ref") in byid:
            ve.append({"from": uid, "to": d["ref"], "arrows": "to", "dashes": [4, 4],
                       "color": {"color": "#e15759"}, "label": d.get("rel", ""),
                       "font": {"size": 10, "color": "#e15759"}})

for n in pending:                               # parked: bottom lane, greyed, still on the time axis
    t, uid = n["value"].get("type"), n["uuid"]
    vn.append({"id": uid, "label": n["value"].get("title", ""), "shape": SHAPE.get(t, "dot"),
               "x": xpos(uid), "y": PENDING_LANE * YS, "fixed": True,
               "color": {"background": "#f5f5f5", "border": "#cccccc"}, "font": {"color": "#aaaaaa"},
               "title": f'PENDING · {t} · {n["value"].get("day","")}'})

HTML = """<!doctype html><html><head><meta charset="utf-8">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>body{margin:0;font-family:sans-serif}#net{width:100vw;height:100vh}
#leg{position:fixed;top:8px;left:8px;z-index:9;background:#fff;padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;line-height:1.6}</style>
</head><body>
<div id="leg"><b>x = time →</b> &nbsp; y = activity lane &nbsp;|&nbsp; ● decision ■ action ▲ issue <span style="color:#aaa">○ pending(bottom)</span><br>
<span style="color:#999">— belongs-to</span> &nbsp; <span style="color:#666">- - caused-by →</span> &nbsp; <span style="color:#e15759">- - diff →</span></div>
<div id="net"></div>
<script>
const nodes = new vis.DataSet(%s);
const edges = new vis.DataSet(%s);
new vis.Network(document.getElementById('net'), {nodes, edges}, {
  physics:false, interaction:{dragNodes:false},
  edges:{smooth:{type:"cubicBezier","forceDirection":"horizontal","roundness":0.4}}, nodes:{font:{size:12}}
});
</script></body></html>""" % (json.dumps(vn, ensure_ascii=False), json.dumps(ve, ensure_ascii=False))

out = f"graph_{BACKEND}.html"
open(out, "w", encoding="utf-8").write(HTML)
print(f"-> {out}  ({len(act_ids)} activities, {len(nodes)-len(act_ids)} placed, {len(pending)} pending)")
