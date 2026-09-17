"""Single-stage sorting pipeline: NanoDet decides normal/abnormal per box, tracks decide per item.

The detector already answers "is this item a reject", so there is no crop-and-classify
second stage any more. What survives from the two-stage version is the part that was never
about the classifier: a item is seen over many frames, and the per-frame call is not the
decision.

Scores are accumulated per track and reduced with MAX, not a mean or EMA. A defect that is
only visible on one side shows up in a handful of frames, and averaging washes it out.
`--min-hits` is what suppresses single-frame false positives -- that is the job averaging
was doing wrong.

    python pipeline.py --source /path/to/video.mp4 --thr 0.6 --save out.mp4
"""
import os
import sys
import time
import argparse
import collections

import cv2
import torch

# Stage 1 lives in detect_item.py so it can be run and inspected on its own.
# Runnable three ways: `python -m ai_part.src.pipeline` from the repo root, `python
# pipeline.py` from this directory, and `python -m pipeline` from this directory. Only the
# first puts the repo root on sys.path, and without it the absolute import below fails --
# so put it there when we were not launched as part of the package.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from ai_part.src.detect_item import Detector

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_CFG = os.path.join(REPO, "src", "config", "nanodet-plus-m-1.5x_416_binary.yml")
DEF_DET = os.path.join(REPO, "runs", "nanodet_binary", "model_best",
                       "nanodet_model_best.pth")

NAMES = ["normal", "abnormal"]
ABNORMAL = 1


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


class Track:
    __slots__ = ("id", "box", "n_obs", "missed", "max_score", "hits", "seen")

    def __init__(self, tid, box):
        self.id = tid
        self.box = box
        self.n_obs = 0
        self.missed = 0
        self.max_score = 0.0
        self.hits = 0
        self.seen = collections.Counter()

    def observe(self, cls_id, score, thr):
        """One view of this item.

        The reject score of a view is the abnormal-class confidence; a box the detector
        called normal contributes 0 rather than `1 - score`. The two classes come out of
        separate per-class NMS, so a normal box is not evidence *against* a lesion on the
        far side -- it is just a view where none was seen, and MAX already handles that.
        """
        self.n_obs += 1
        self.seen[NAMES[int(cls_id)]] += 1
        s = float(score) if int(cls_id) == ABNORMAL else 0.0
        self.max_score = max(self.max_score, s)
        if s > thr:
            self.hits += 1

    def verdict(self, thr, min_hits):
        return self.max_score > thr and self.hits >= min_hits


class Tracker:
    """Greedy IoU association. A conveyor moves items on a smooth, near-linear path with
    little occlusion, so this is enough -- swap in ByteTrack only if the belt gets crowded.

    Measured caveat on the SB clips: the belt moves ~155 px per frame against a ~219 px
    box, so the same item overlaps itself by a median IoU of 0.139 and this association
    fails almost every frame. That footage is free-running capture; on an encoder-triggered
    camera the per-frame displacement is constant and this holds. If you are working with
    free-running clips, use export_tracks.py's phase clustering instead."""

    def __init__(self, iou_thr=0.3, max_missed=5):
        self.iou_thr = iou_thr
        self.max_missed = max_missed
        self.tracks = []
        self.next_id = 0

    def update(self, boxes):
        for t in self.tracks:
            t.missed += 1

        assigned = set()
        for box in boxes:
            best, best_iou = None, self.iou_thr
            for t in self.tracks:
                if t.id in assigned:
                    continue
                v = iou(box, t.box)
                if v > best_iou:
                    best, best_iou = t, v
            if best is None:
                best = Track(self.next_id, box)
                self.next_id += 1
                self.tracks.append(best)
            best.box = box
            best.missed = 0
            assigned.add(best.id)

        finished = [t for t in self.tracks if t.missed > self.max_missed]
        self.tracks = [t for t in self.tracks if t.missed <= self.max_missed]
        return [t for t in self.tracks if t.missed == 0], finished


def crop(frame, box, pad):
    """Kept here rather than inlined at the call site: export_tracks.py imports it so the
    crops it writes for review are cut exactly the way the live path would cut them."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box[:4]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    bw, bh = (x2 - x1) * (1 + pad), (y2 - y1) * (1 + pad)
    x1 = int(max(0, cx - bw / 2)); x2 = int(min(w, cx + bw / 2))
    y1 = int(max(0, cy - bh / 2)); y2 = int(min(h, cy + bh / 2))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    return frame[y1:y2, x1:x2]

def parsing_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=str, default="0",
                        help="video file or camera index")
    parser.add_argument("--config", type=str, default=DEF_CFG,
                        help="detector config file")
    parser.add_argument("--weights", type=str, default=DEF_DET,
                        help="detector weights file")
    parser.add_argument("--det-thr", type=float, default=0.5,
                        help="detector confidence threshold")
    parser.add_argument("--thr", type=float, default=0.6,
                        help="track verdict threshold")
    parser.add_argument("--min-hits", type=int, default=3,
                        help="track verdict minimum hits")
    parser.add_argument("--save", type=str, default=None,
                        help="save annotated video to this path")
    parser.add_argument("--show", action="store_true",
                        help="show annotated video in a window")
    return parser.parse_args()


def main():
    args = parsing_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.backends.cudnn.benchmark = True

    detector = Detector(args.config, args.weights, device)
    tracker = Tracker()
    print(f"device {device}  weights {args.weights}")

    src = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"cannot open source: {args.source}")

    writer = None
    if args.save:
        # VideoWriter returns a dead object instead of raising when the parent folder is
        # missing, so the run looks fine and writes nothing.
        os.makedirs(os.path.dirname(os.path.abspath(args.save)), exist_ok=True)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        wh = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), fps, wh)
        if not writer.isOpened():
            raise SystemExit(f"cannot open video writer for {args.save}")

    # First frames pay for lazy CUDA init and cudnn.benchmark autotuning. Averaging them in
    # makes the reported throughput meaningless on short clips.
    WARMUP = 5
    tally = collections.Counter()
    det_ms = 0.0
    frame_i = timed = 0

    def report(t):
        if t.n_obs == 0:
            return
        bad = t.verdict(args.thr, args.min_hits)
        tally["abnormal" if bad else "normal"] += 1
        # flush: verdicts are the live output of a sorting run, and block buffering would
        # strand them whenever stdout is piped to a log or a downstream process.
        print(f"track {t.id:>4}  {t.n_obs:>3} views  max {t.max_score:.3f}  "
              f"hits {t.hits}  {dict(t.seen)}  -> {'REJECT' if bad else 'PASS'}",
              flush=True)

    t_start = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        t0 = time.time()
        boxes = detector(frame, args.det_thr, with_class=True)
        t1 = time.time()

        live, finished = tracker.update(boxes)
        for t in live:
            t.observe(t.box[5], t.box[4], args.thr)

        if frame_i == WARMUP:
            t_start = time.time()
        if frame_i >= WARMUP:
            det_ms += (t1 - t0) * 1000
            timed += 1

        for t in finished:
            report(t)

        if writer or args.show:
            for t in live:
                bad = t.verdict(args.thr, args.min_hits)
                color = (0, 0, 255) if bad else (0, 200, 0)
                x1, y1, x2, y2 = (int(v) for v in t.box[:4])
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"#{t.id} {t.max_score:.2f}", (x1, max(14, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            if writer:
                writer.write(frame)
            if args.show:
                cv2.imshow("item", frame)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break

        frame_i += 1

    # Tracks still alive when the source ends still deserve a verdict -- and it has to be
    # printed, not just tallied, or the per-track log silently disagrees with the total.
    for t in tracker.tracks:
        report(t)

    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()

    elapsed, n = time.time() - t_start, max(timed, 1)
    print(f"\n{frame_i} frames ({timed} timed after {WARMUP} warmup) "
          f"in {elapsed:.1f}s  ({n / elapsed:.1f} fps)")
    print(f"  detect {det_ms / n:.1f} ms/frame")
    print(f"  items: {tally['normal']} pass / {tally['abnormal']} reject")


if __name__ == "__main__":
    main()
