"""Post-extraction step 2 of 2: remove wheel-pocket ghost boxes from the labeling set.

The web-photo-trained 1-class detector boxes empty cup-carrier wheel pockets as potatoes: wide
~2:1 boxes at confidence 0.50-0.65. Real potatoes are ~1:1, and the few genuinely elongated
potatoes score >= 0.70, so the rule is

    ghost := label box with aspect >= 2.0 AND re-detected conf < 0.65
             (or no re-detected box >= 0.5 overlapping it at IoU >= 0.5)

Frames left with no box are moved (not deleted) to data_test/ghost_frames/<lane>/, mixed
frames keep only their real boxes, manifests are rewritten with the new n_boxes. Rows whose
image no longer exists (deleted by hand) are dropped too, so images = labels = manifest again.
On the 2026-09-07 set: 12,756 boxes removed, 9,558 frames quarantined, 1,879 frames trimmed.

    python wheel_ghost_clean.py redetect1.csv [redetect2.csv ...]          # dry run
    python wheel_ghost_clean.py redetect1.csv [redetect2.csv ...] --apply

Paths are hardcoded for that run (data_test/labeling_all{,_2,_3}/cam{0..3}).
"""
import os, sys, csv, shutil, collections

DT = os.environ.get("DATA_TEST_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data_test")); W, H = 1280, 1024
ASP, CONF, IOU = 2.0, 0.65, 0.5
APPLY = "--apply" in sys.argv
Q = os.path.join(DT, "ghost_frames")

redet = collections.defaultdict(list)
for f in [a for a in sys.argv[1:] if a != "--apply"]:
    for r in csv.DictReader(open(f)):
        if float(r["conf"]) >= 0.5:
            redet[(r["lane"], r["name"])].append((int(r["x1"]), int(r["y1"]), int(r["x2"]), int(r["y2"]), float(r["conf"])))


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    return i / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i + 1e-9)


tot = collections.Counter()
print(f"{'lane':<20} {'frames':>6} {'ghostbox':>8} {'quarant':>7} {'trimmed':>7} {'orphan':>6} {'remain':>6}")
for d in ["labeling_all", "labeling_all_2", "labeling_all_3"]:
    for c in ["cam0", "cam1", "cam2", "cam3"]:
        lane = f"{d}/{c}"; p = os.path.join(DT, lane)
        rows = list(csv.reader(open(os.path.join(p, "manifest.csv")))); head, body = rows[0], rows[1:]
        imgs = {f[:-4] for f in os.listdir(os.path.join(p, "images"))}
        st = collections.Counter(); newbody = []
        for r in body:
            name = f"{r[0]}_f{int(r[1]):05d}"
            if name not in imgs:                       # image deleted by hand -> drop label + row
                st["orphan"] += 1
                if APPLY:
                    lp = os.path.join(p, "labels", name + ".txt"); os.path.isfile(lp) and os.remove(lp)
                continue
            lines = [l.split() for l in open(os.path.join(p, "labels", name + ".txt")) if l.strip()]
            keep = []
            for l in lines:
                cx, cy, bw, bh = (float(v) for v in l[1:5])
                px = (int((cx-bw/2)*W), int((cy-bh/2)*H), int((cx+bw/2)*W), int((cy+bh/2)*H))
                if bw * W / (bh * H) >= ASP:
                    m = [b for b in redet.get((lane, name), []) if iou(px, b) >= IOU]
                    conf = max((b[4] for b in m), default=0.0)
                    if conf < CONF:
                        st["ghostbox"] += 1; continue
                keep.append(l)
            if not keep:
                st["quarant"] += 1
                if APPLY:
                    qd = os.path.join(Q, lane)
                    os.makedirs(os.path.join(qd, "images"), exist_ok=True); os.makedirs(os.path.join(qd, "labels"), exist_ok=True)
                    try:
                        shutil.move(os.path.join(p, "images", name + ".jpg"), os.path.join(qd, "images", name + ".jpg"))
                    except FileNotFoundError:
                        st["orphan"] += 1; st["quarant"] -= 1      # deleted by hand between listing and move
                    lp = os.path.join(p, "labels", name + ".txt")
                    os.path.isfile(lp) and shutil.move(lp, os.path.join(qd, "labels", name + ".txt"))
                continue
            if len(keep) != len(lines):
                st["trimmed"] += 1
                if APPLY:
                    with open(os.path.join(p, "labels", name + ".txt"), "w") as f:
                        f.write("\n".join(" ".join(l) for l in keep) + "\n")
                r = r[:3] + [str(len(keep)), r[4]]        # max_conf no longer exact for trimmed frames; n_boxes is
            newbody.append(r); st["remain"] += 1
        if APPLY:
            with open(os.path.join(p, "manifest.csv"), "w", newline="") as f:
                w = csv.writer(f); w.writerow(head); w.writerows(newbody)
        print(f"{lane:<20} {len(body):>6} {st['ghostbox']:>8} {st['quarant']:>7} {st['trimmed']:>7} {st['orphan']:>6} {st['remain']:>6}")
        tot.update(st); tot["frames"] += len(body)
print(f"{'TOTAL':<20} {tot['frames']:>6} {tot['ghostbox']:>8} {tot['quarant']:>7} {tot['trimmed']:>7} {tot['orphan']:>6} {tot['remain']:>6}")
print("APPLIED" if APPLY else "DRY RUN — nothing written")
