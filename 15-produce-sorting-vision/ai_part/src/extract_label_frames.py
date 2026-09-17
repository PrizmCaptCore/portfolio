"""Pull labelling frames out of raw belt footage: only frames with a potato, ~3 per second.

Five minutes of 15 fps video is 4,500 frames, most of them either empty carrier or the same
potato three pixels further along. Neither is worth a labeller's time. This walks each
video, keeps a frame only when the potato detector sees one in it, and then only on a fixed
schedule of --fps per second -- so the output is N frames per second *of potato-visible
time*, and stretches of empty carrier contribute nothing.

Presence is decided by the single-class potato detector (runs/nanodet_potato), not the
normal/abnormal one. That is deliberate: on the 2026-09-04 rig footage the two-class model
boxed empty cup pockets as "abnormal" in 88% of the frames it flagged -- it had never seen
a dark cup carrier and could not tell a pocket from a potato. The single-class model, trained
on 17.8k images for exactly the question "is there a potato", was right on every frame
checked by hand. One model, one question.

Each kept frame gets a YOLO pre-label with the detector's boxes so the labeller checks and
classifies rather than draws. The class is a 0 placeholder: this model has no class to
offer, and the two-class model's class is noise on this footage.

Layout is the images/ + labels/ sibling pair that LabelImg, CVAT and Roboflow all import:

    data_test/labeling/
      images/  cam0_..._000_f00123.jpg
      labels/  cam0_..._000_f00123.txt      class 0 placeholder + box
      classes.txt
      manifest.csv        video, frame, t_sec, n_boxes, max_conf

    python extract_label_frames.py --fps 6
    python extract_label_frames.py --src ../../data_test --fps 3 --det-thr 0.5
"""
import os
import csv
import glob
import argparse

import cv2
import torch

from detect_potato import Detector, DEF_CFG, DEF_DET, REPO, VIDEO_EXT

SRC = os.path.join(os.path.dirname(REPO), "data_test")


def to_yolo(box, w, h):
    x1, y1, x2, y2 = box[:4]
    return (f"0 {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} "
            f"{(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")


def extract(det, path, out, args, writer):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print(f"  cannot open {path}")
        return 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stem = os.path.splitext(os.path.basename(path))[0]
    min_gap = 1.0 / args.fps

    kept = 0
    next_due = -1e9
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = i / fps
        if i % args.stride == 0 and t >= next_due:
            boxes = det(frame, args.det_thr)
            if boxes:
                h, w = frame.shape[:2]
                name = f"{stem}_f{i:05d}"
                cv2.imwrite(os.path.join(out, "images", name + ".jpg"), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 95])
                with open(os.path.join(out, "labels", name + ".txt"), "w") as f:
                    f.write("\n".join(to_yolo(b, w, h) for b in boxes) + "\n")
                writer.writerow([stem, i, f"{t:.3f}", len(boxes),
                                 f"{max(b[4] for b in boxes):.3f}"])
                kept += 1
                # Advance from the *schedule*, not from the frame we happened to save.
                # Frames land on a 1/15 s grid and 1/6 s is 2.5 of them; measuring from
                # the last save always rounds up to 3 frames and delivers 5/s instead of
                # 6. Stepping the due time by exactly min_gap lets the gaps alternate
                # 2, 3, 2, 3 and the average land on target. If the belt has been empty
                # for a while the schedule is stale, so restart it from now rather than
                # let a backlog dump several frames in a row.
                next_due = (next_due if t - next_due < min_gap else t) + min_gap
        i += 1
        if i % 500 == 0:
            print(f"  {stem}  {i}/{n}  kept {kept}", end="\r", flush=True)
    cap.release()
    print(f"  {stem}  {i} frames -> {kept} kept  "
          f"({kept / max(i / fps, 1e-9):.2f}/s of video, target {args.fps}/s of potato time)")
    return kept


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=SRC, help="folder of videos")
    p.add_argument("--out", default=os.path.join(SRC, "labeling"))
    p.add_argument("--config", default=DEF_CFG)
    p.add_argument("--weights", default=DEF_DET)
    p.add_argument("--fps", type=float, default=3.0, help="frames kept per second of potato time")
    p.add_argument("--det-thr", type=float, default=0.5,
                   help="presence floor. On this footage real potatoes score 0.64-0.81 "
                        "(p10-p90); 0.5 keeps the edge-clipped ones too, which a labeller "
                        "can skip far more cheaply than we can recover a missed frame")
    p.add_argument("--stride", type=int, default=1,
                   help="inspect every Nth frame. >1 halves inference but quantises the "
                        "save interval to multiples of stride/fps, so the kept rate lands "
                        "below --fps; leave at 1 unless the rate does not matter")
    p.add_argument("--limit", type=int, default=0, help="cap videos (0 = all)")
    args = p.parse_args()

    vids = sorted(v for v in glob.glob(os.path.join(args.src, "*"))
                  if v.lower().endswith(VIDEO_EXT))
    if args.limit:
        vids = vids[:args.limit]
    if not vids:
        raise SystemExit(f"no videos in {args.src}")

    for d in ("images", "labels"):
        os.makedirs(os.path.join(args.out, d), exist_ok=True)
    with open(os.path.join(args.out, "classes.txt"), "w") as f:
        f.write("normal\nabnormal\n")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    det = Detector(args.config, args.weights, device)
    print(f"device {device}  weights {args.weights}")
    print(f"{len(vids)} videos -> {args.out}")

    total = 0
    with open(os.path.join(args.out, "manifest.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["video", "frame", "t_sec", "n_boxes", "max_conf"])
        for v in vids:
            total += extract(det, v, args.out, args, wr)

    print(f"\n{total} frames -> {args.out}/images  (pre-labels in labels/)")


if __name__ == "__main__":
    main()
