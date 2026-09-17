"""Group each potato in a clip into its own folder of crops, keyed off a reference line.

Frame-to-frame tracking does not work on this footage and the numbers say why: the belt
moves ~155 px per frame while a potato box is ~219 px across, so the SAME potato on two
consecutive frames overlaps itself by a median IoU of 0.139 -- under pipeline.Tracker's
iou_thr of 0.3. Association fails almost every frame, one potato becomes several ids, and
the count wanders (9-12 on clips that hold exactly 10).

So identity is not chased across frames here. The belt speed is constant, so for a
detection on frame i with centre cx, the frame at which that potato touches the line
x = LINE_X is

    phase = i + (LINE_X - cx) / dx

Every detection of the same potato yields the same phase, whatever frame it came from.
Cluster (phase, cy) and each cluster is one physical potato -- nothing is associated frame
to frame, so there is no chain to break. Potato ids are then handed out in crossing order,
which is belt order. On the 10 SB clips (10 potatoes each) this returns exactly 10 on 9 of
them, and 11 on one.

LINE_X shifts every phase by the same constant, so it cannot change the grouping -- it only
decides which frame is recorded as the crossing, i.e. which view is the canonical one.

    runs/tracks/SB_burst00/potato_00/f00019.jpg   <- first potato over the line
                                    /f00021.jpg
                          potato_01/...
                          contact/potato_00.jpg   <- one potato, all its views, one sheet
                          potatoes.csv

Two passes over the clip: detect and solve identity first, then re-read and crop. Detection
is the expensive pass; the second is decode-and-write, and it keeps memory flat instead of
holding every frame.

pipeline.py is unchanged and still runs its own live tracker -- this is an offline tool and
the phase trick needs the whole clip in hand. That tracker has the same weakness measured
above; see the note at the bottom of this file.

Set the constants below and run `python export_tracks.py`.
"""
import os
import sys
import csv
import glob
import types
import shutil
import statistics
import collections

import cv2
import torch
import numpy as np

# Runnable three ways: `python -m ai_part.src.pipeline` from the repo root, `python
# pipeline.py` from this directory, and `python -m pipeline` from this directory. Only the
# first puts the repo root on sys.path, and without it the absolute import below fails --
# so put it there when we were not launched as part of the package.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from ai_part.src.detect_potato import Detector, DEF_CFG, DEF_DET, REPO, VIDEO_EXT
from ai_part.src.pipeline import crop          # one crop rule, shared with the live pipeline

# Edit these and run the file -- no CLI, same as detect_potato.py.
SOURCE = os.path.join(REPO, "runs", "video", "SB")   # clip, or a folder of clips
OUT = os.path.join(REPO, "runs", "tracks")
CONFIG = DEF_CFG
WEIGHTS = DEF_DET
DET_THR = 0.20       # detect_potato's default. Clustering tolerates a loose threshold far
                     # better than tracking did -- a stray box lands on its own phase and is
                     # dropped by MIN_VIEWS instead of corrupting a chain
P_TOL = 0.7          # phase tolerance, in frames. Two detections closer than this are the
                     # same potato. Swept on the SB clips: 0.5-0.7 is the flat spot
Y_TOL = 150          # px. Separates the two lanes. Not tighter: a box clipped at the frame
                     # edge pulls its own centre ~110 px off, and at 100 that split a real
                     # potato in two. 60-300 all hold the count; this is the middle of it
MIN_VIEWS = 3        # drop clusters with fewer crops -- those are flicker, not potatoes
LINE_X = None        # crossing line in px; None = frame centre, where a potato is whole
PAD = 0.08           # box expansion before cropping; skin defects sit on the silhouette
MIN_PX = 48          # drop crops shorter than this; a 20px lesion crop is noise
EDGE_MARGIN = 4      # px. A box touching the frame border is a partial potato -- a lesion
                     # call on half a potato is worse than no call, so those views are cut
CONTACT = True       # write the per-potato contact sheet
LIMIT = 0            # cap clip count (0 = all)


def detect_clip(detector, path, det_thr):
    """Pass 1: every box of every frame. Cheap to hold -- a clip is a few hundred boxes."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    dets, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for box in detector(frame, det_thr):
            dets.append((i, box))
        i += 1
    cap.release()
    return dets, i, (w, h)


def estimate_dx(dets, width):
    """Belt displacement per frame, in px, from the detections themselves.

    Measuring it per clip rather than hard-coding: the SB clips come out between -139 and
    -165, and a wrong dx smears every phase, which is the one thing this method cannot
    tolerate. Scored by how tightly the phases bunch up -- the true dx is the one that
    collapses each potato's detections onto a single value.
    """
    if len(dets) < 20:
        return None

    best_score, best_dx = None, None
    for cand in np.arange(-width / 4, -width / 64, 0.5):
        ph = sorted(i - cx(box) / cand for i, box in dets)
        gaps = sorted(b - a for a, b in zip(ph, ph[1:]))
        # Sum only the small gaps: those are within-potato spread. The large ones are the
        # gaps *between* potatoes and should stay large, so leaving them out of the score
        # stops it from being minimised by simply crushing everything together.
        score = sum(gaps[:int(len(gaps) * 0.75)])
        if best_score is None or score < best_score:
            best_score, best_dx = score, float(cand)
    return best_dx


def cx(box):
    return (box[0] + box[2]) / 2


def cy(box):
    return (box[1] + box[3]) / 2


def assign(dets, dx, line_x, p_tol, y_tol, min_views):
    """Cluster detections by (phase, cy). Returns [[(frame, box), ...], ...] in belt order."""
    pts = sorted(((i + (line_x - cx(box)) / dx, i, box) for i, box in dets),
                 key=lambda p: p[0])

    clusters = []          # each: {"phase": last phase seen, "items": [...], "ys": [...]}
    for phase, i, box in pts:
        # Nearest open cluster, not merely the first that fits -- with potatoes tight on the
        # belt the first match in creation order is not always the right one.
        best, best_d = None, p_tol
        for c in clusters:
            d = phase - c["phase"]
            if d <= best_d and any(abs(cy(box) - y) <= y_tol for y in c["ys"]):
                best, best_d = c, d
        if best is None:
            best = {"phase": phase, "items": [], "ys": []}
            clusters.append(best)
        best["phase"] = phase
        best["items"].append((i, box))
        best["ys"].append(cy(box))

    keep = [c for c in clusters if len(c["items"]) >= min_views]
    keep.sort(key=lambda c: statistics.median(
        i + (line_x - cx(box)) / dx for i, box in c["items"]))
    return [sorted(c["items"]) for c in keep], len(clusters) - len(keep)


def contact_sheet(folder, cols=4, cell=160, limit=12):
    """One potato, up to `limit` views evenly spaced over its life, tiled into one image."""
    paths = sorted(glob.glob(os.path.join(folder, "f*.jpg")))
    if not paths:
        return None

    # Evenly spaced over the crossing, not the first 12: the point is to see every side the
    # potato turned, and consecutive frames are all one side.
    idx = np.linspace(0, len(paths) - 1, min(limit, len(paths))).round().astype(int)
    picks = [paths[i] for i in dict.fromkeys(idx.tolist())]

    rows = -(-len(picks) // cols)
    sheet = np.zeros((rows * cell, cols * cell, 3), np.uint8)
    for k, path in enumerate(picks):
        img = cv2.imread(path)
        if img is None:
            continue
        r, c = divmod(k, cols)
        tile = cv2.resize(img, (cell, cell), interpolation=cv2.INTER_AREA)
        cv2.putText(tile, os.path.splitext(os.path.basename(path))[0], (4, cell - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 220, 255), 1)
        sheet[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = tile
    return sheet


def export_clip(detector, path, out_root, args):
    dets, n_frames, (w, h) = detect_clip(detector, path, args.det_thr)
    dx = estimate_dx(dets, w)
    if dx is None:
        print(f"  only {len(dets)} detections -- too few to solve belt speed, skipped")
        return 0, 0

    line_x = w / 2 if args.line_x is None else args.line_x
    potatoes, dropped = assign(dets, dx, line_x, args.p_tol, args.y_tol, args.min_views)

    # A rerun must not merge into the previous run's folders -- stale crops from an older
    # threshold would silently pollute whatever you look at next.
    if os.path.isdir(out_root):
        shutil.rmtree(out_root)
    os.makedirs(out_root)

    # Pass 2: which crops to cut from which frame, now that identity is settled.
    want = collections.defaultdict(list)     # frame -> [(potato_id, box), ...]
    for pid, items in enumerate(potatoes):
        for i, box in items:
            want[i].append((pid, box))

    kept = collections.Counter()
    edge = collections.Counter()
    small = collections.Counter()
    score_sum = collections.Counter()
    seen = {pid: len(items) for pid, items in enumerate(potatoes)}

    cap = cv2.VideoCapture(path)
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for pid, box in want.get(i, []):
            # A box against the frame border is a potato half out of shot; classifying that
            # is worse than not classifying it, and the belt gives us whole views anyway.
            if (box[0] <= args.edge_margin or box[1] <= args.edge_margin
                    or box[2] >= w - args.edge_margin or box[3] >= h - args.edge_margin):
                edge[pid] += 1
                continue
            c = crop(frame, box, args.pad)
            if c is None or min(c.shape[:2]) < args.min_px:
                small[pid] += 1
                continue
            d = os.path.join(out_root, f"potato_{pid:02d}")
            os.makedirs(d, exist_ok=True)
            cv2.imwrite(os.path.join(d, f"f{i:05d}.jpg"), c, [cv2.IMWRITE_JPEG_QUALITY, 95])
            kept[pid] += 1
            score_sum[pid] += float(box[4])
        i += 1
    cap.release()

    if args.contact and kept:
        os.makedirs(os.path.join(out_root, "contact"), exist_ok=True)
        for pid in sorted(kept):
            sheet = contact_sheet(os.path.join(out_root, f"potato_{pid:02d}"))
            if sheet is not None:
                cv2.imwrite(os.path.join(out_root, "contact", f"potato_{pid:02d}.jpg"), sheet)

    with open(os.path.join(out_root, "potatoes.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["potato_id", "n_crops", "n_views", "cross_frame", "first_frame",
                     "last_frame", "y_center", "mean_det_score", "n_edge", "n_too_small",
                     "folder"])
        for pid, items in enumerate(potatoes):
            if not kept[pid]:
                continue
            frames = [i for i, _ in items]
            phase = statistics.median(i + (line_x - cx(box)) / dx for i, box in items)
            wr.writerow([pid, kept[pid], seen[pid], round(phase, 1), min(frames), max(frames),
                         round(statistics.median(cy(box) for _, box in items)),
                         round(score_sum[pid] / kept[pid], 3), edge[pid], small[pid],
                         f"potato_{pid:02d}"])

    print(f"  {n_frames} frames, {len(dets)} boxes, belt {dx:+.0f} px/frame"
          f" -> {len(kept)} potatoes, {sum(kept.values())} crops"
          f"  ({dropped} clusters under {args.min_views} views)", flush=True)
    return len(kept), sum(kept.values())


def main():
    args = types.SimpleNamespace(det_thr=DET_THR, p_tol=P_TOL, y_tol=Y_TOL,
                                 min_views=MIN_VIEWS, line_x=LINE_X, pad=PAD,
                                 min_px=MIN_PX, edge_margin=EDGE_MARGIN, contact=CONTACT)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.backends.cudnn.benchmark = True
    detector = Detector(CONFIG, WEIGHTS, device)
    print(f"device {device}  weights {WEIGHTS}")

    if os.path.isdir(SOURCE):
        clips = sorted(f for f in glob.glob(os.path.join(SOURCE, "*"))
                       if f.lower().endswith(VIDEO_EXT))
        if not clips:
            raise SystemExit(f"no videos in {SOURCE}")
    else:
        clips = [SOURCE]
    if LIMIT:
        clips = clips[:LIMIT]

    n_pot = n_crop = 0
    for path in clips:
        stem = os.path.splitext(os.path.basename(path))[0]
        print(f"\n=== {stem}")
        # Per clip, so potato ids from different clips cannot collide in one folder.
        p, c = export_clip(detector, path, os.path.join(OUT, stem), args)
        n_pot += p
        n_crop += c

    print(f"\n{len(clips)} clips, {n_pot} potatoes, {n_crop} crops -> {OUT}")


if __name__ == "__main__":
    main()
