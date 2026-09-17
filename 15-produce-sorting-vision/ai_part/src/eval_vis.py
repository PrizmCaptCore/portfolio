"""Render what the two-class detector actually predicted, sorted so the failures are first.

NanoDet's evaluator prints mAP and writes a results json. Neither tells you *how* the model
is wrong, and for a sorting line the how is the whole question: mAP treats a normal potato
called abnormal and an abnormal one called normal as the same 0.5-point loss, when one
costs you a good potato and the other ships a bad one to a customer.

So this buckets every image by what went wrong and writes it to its own folder:

    ok/            every box matched, right class
    false_reject/  a normal potato called abnormal   <- you throw away good produce
    false_accept/  an abnormal potato called normal  <- a defect reaches the customer
    ghost/         a box where there is no potato
    missed/        a potato with no box at all

Open false_reject/ and false_accept/ first; ok/ is there to confirm the good case looks
sane, not to be browsed. Ground truth is drawn as a thin white box, the prediction as a
thick coloured one, so a disagreement is visible without reading labels.

    python eval_vis.py                       # labelled test split, buckets + summary
    python eval_vis.py --source ../runs/video/SB --limit 40
    python eval_vis.py --source ../runs/video/SB/SB_burst00.mp4 --save-video out.mp4

With --source pointing at unlabelled images or a video there is no ground truth, so
everything is drawn and nothing is bucketed -- that is the rig-footage case, where the
question is only ever "does this look right".
"""
import os
import glob
import shutil
import argparse
import collections

import cv2
import torch

from detect_potato import Detector, REPO, IMAGE_EXT, VIDEO_EXT

CFG = os.path.join(REPO, "src", "config", "nanodet-plus-m-1.5x_416_binary.yml")
CKPT = os.path.join(REPO, "runs", "nanodet_binary", "model_best", "nanodet_model_best.pth")
TEST = os.path.join(REPO, "datasets", "potato_binary_nanodet", "test")
OUT = os.path.join(REPO, "runs", "binary_vis")

NAMES = ["normal", "abnormal"]
COLOR = {0: (0, 200, 0), 1: (0, 0, 255)}     # normal green, abnormal red (BGR)
GT_COLOR = (255, 255, 255)


def read_labels(txt, w, h):
    """YOLO normalised cx cy bw bh -> pixel xyxy plus class id."""
    out = []
    if not os.path.isfile(txt):
        return out
    with open(txt) as f:
        for line in f:
            p = line.split()
            if len(p) < 5:
                continue
            cid = int(p[0])
            cx, cy, bw, bh = (float(v) for v in p[1:5])
            out.append((int((cx - bw / 2) * w), int((cy - bh / 2) * h),
                        int((cx + bw / 2) * w), int((cy + bh / 2) * h), cid))
    return out


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    aa = (a[2] - a[0]) * (a[3] - a[1])
    ab = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (aa + ab - inter)


def match(preds, gts, thr):
    """Greedy highest-IoU pairing. Returns (pairs, unmatched preds, unmatched gts).

    Greedy rather than Hungarian: boxes here are whole potatoes that barely overlap each
    other, so the assignment is never ambiguous enough for the difference to show.
    """
    pairs, used = [], set()
    for pi, p in enumerate(sorted(range(len(preds)), key=lambda i: -preds[i][4])):
        best, best_iou = None, thr
        for gi, g in enumerate(gts):
            if gi in used:
                continue
            v = iou(preds[p], g)
            if v > best_iou:
                best, best_iou = gi, v
        if best is not None:
            used.add(best)
            pairs.append((p, best))
    matched_p = {p for p, _ in pairs}
    return (pairs,
            [i for i in range(len(preds)) if i not in matched_p],
            [i for i in range(len(gts)) if i not in used])


def draw(img, preds, gts=None):
    for g in (gts or []):
        cv2.rectangle(img, (g[0], g[1]), (g[2], g[3]), GT_COLOR, 1)
    for x1, y1, x2, y2, s, cid in preds:
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        c = COLOR.get(int(cid), (200, 200, 0))
        cv2.rectangle(img, (x1, y1), (x2, y2), c, 3)
        cv2.putText(img, f"{NAMES[int(cid)]} {s:.2f}", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 2)
    return img


def run_labeled(det, args):
    paths = sorted(p for p in glob.glob(os.path.join(args.test, "*"))
                   if p.lower().endswith(IMAGE_EXT))
    if args.limit:
        paths = paths[:args.limit]
    if not paths:
        raise SystemExit(f"no images in {args.test}")

    for b in ("ok", "false_reject", "false_accept", "ghost", "missed"):
        d = os.path.join(args.out, b)
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

    tally = collections.Counter()
    confusion = collections.Counter()
    for path in paths:
        img = cv2.imread(path)
        if img is None:
            continue
        h, w = img.shape[:2]
        gts = read_labels(os.path.splitext(path)[0] + ".txt", w, h)
        preds = det(img, args.det_thr, with_class=True)

        pairs, extra, missed = match(preds, gts, args.iou_thr)
        buckets = set()
        for pi, gi in pairs:
            pc, gc = int(preds[pi][5]), gts[gi][4]
            confusion[(NAMES[gc], NAMES[pc])] += 1
            if pc != gc:
                buckets.add("false_reject" if gc == 0 else "false_accept")
        if extra:
            buckets.add("ghost")
        if missed:
            buckets.add("missed")
            for gi in missed:
                confusion[(NAMES[gts[gi][4]], "missed")] += 1
        for pi in extra:
            confusion[("ghost", NAMES[int(preds[pi][5])])] += 1

        # An image lands in every bucket it earned. A picture with both a false reject and
        # a miss is evidence for both, and copying it twice is cheaper than making someone
        # hunt for it in whichever single folder we happened to pick.
        for b in (buckets or {"ok"}):
            tally[b] += 1
            cv2.imwrite(os.path.join(args.out, b, os.path.basename(path)),
                        draw(img.copy(), preds, gts))

    print(f"\n{len(paths)} images -> {args.out}")
    for b in ("ok", "false_reject", "false_accept", "ghost", "missed"):
        print(f"  {b:<14} {tally[b]:>5}  ({tally[b] / len(paths):.1%})")

    print("\n  box-level, ground truth -> prediction:")
    for gt in NAMES + ["ghost"]:
        row = {p: n for (g, p), n in confusion.items() if g == gt}
        if row:
            total = sum(row.values())
            print(f"    {gt:<10} n={total:<6} " +
                  "  ".join(f"{k} {v} ({v / total:.0%})" for k, v in sorted(row.items())))

    fr = confusion[("normal", "abnormal")]
    fa = confusion[("abnormal", "normal")]
    n_norm = sum(v for (g, _), v in confusion.items() if g == "normal")
    n_abn = sum(v for (g, _), v in confusion.items() if g == "abnormal")
    print(f"\n  오배출률 (정상을 불량으로)  {fr}/{n_norm} = {fr / max(n_norm, 1):.1%}")
    print(f"  유출률   (불량을 정상으로)  {fa}/{n_abn} = {fa / max(n_abn, 1):.1%}")
    print("  * det_thr 하나로 잰 값입니다. 임계값을 움직여 만드는 운영표는 아직 없습니다.")


def run_unlabeled(det, args):
    os.makedirs(args.out, exist_ok=True)
    src = args.source
    if os.path.isdir(src):
        paths = sorted(p for p in glob.glob(os.path.join(src, "*"))
                       if p.lower().endswith(IMAGE_EXT))
        vids = sorted(p for p in glob.glob(os.path.join(src, "*"))
                      if p.lower().endswith(VIDEO_EXT))
    else:
        paths = [src] if src.lower().endswith(IMAGE_EXT) else []
        vids = [src] if src.lower().endswith(VIDEO_EXT) else []
    if args.limit:
        paths, vids = paths[:args.limit], vids[:args.limit]

    counts = collections.Counter()
    for path in paths:
        img = cv2.imread(path)
        if img is None:
            continue
        preds = det(img, args.det_thr, with_class=True)
        for b in preds:
            counts[NAMES[int(b[5])]] += 1
        cv2.imwrite(os.path.join(args.out, os.path.basename(path)), draw(img, preds))

    for v in vids:
        cap = cv2.VideoCapture(v)
        stem = os.path.splitext(os.path.basename(v))[0]
        d = os.path.join(args.out, stem)
        os.makedirs(d, exist_ok=True)
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            preds = det(frame, args.det_thr, with_class=True)
            for b in preds:
                counts[NAMES[int(b[5])]] += 1
            cv2.imwrite(os.path.join(d, f"f{i:05d}.jpg"), draw(frame, preds))
            i += 1
        cap.release()
        print(f"  {stem}: {i} frames")

    print(f"\n{len(paths)} images + {len(vids)} videos -> {args.out}")
    print(f"  boxes: {dict(counts)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=CFG)
    p.add_argument("--weights", default=CKPT)
    p.add_argument("--test", default=TEST)
    p.add_argument("--source", default=None,
                   help="unlabelled images/video instead of the test split")
    p.add_argument("--out", default=OUT)
    p.add_argument("--det-thr", type=float, default=0.35)
    p.add_argument("--iou-thr", type=float, default=0.5)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    det = Detector(args.config, args.weights, device)
    print(f"device {device}  weights {args.weights}")

    if args.source:
        run_unlabeled(det, args)
    else:
        run_labeled(det, args)


if __name__ == "__main__":
    main()
