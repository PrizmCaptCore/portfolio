"""Rebuild videos from the captured frame sequences and run detection on them.

The rig saves stills named '<prefix>_YYYYMMDD_HHMMSS_ffffff.png'. Those timestamps
recover both the ordering and the true capture rate, which varies per session
(~0.2 fps up to ~14 fps). A session is not one continuous take -- it is a handful
of short bursts separated by long idle gaps, so by default each burst becomes its
own clip instead of splicing unrelated moments together.

    python video.py build  --frames ../item_img/raw/25.11.05/normal/SB
    python video.py detect --video ../runs/video/SB/SB_burst00.mp4
"""
import os
import re
import csv
import glob
import argparse
import statistics
from datetime import datetime

import cv2
from ultralytics import YOLO

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTS = (".png", ".jpg", ".jpeg", ".bmp")
STAMP = re.compile(r"_(\d{8})_(\d{6})_(\d{6})")

# A gap this many times the median frame interval means the camera stopped and
# restarted -- a cut, not motion.
BURST_FACTOR = 3.0


def timestamp(path):
    m = STAMP.search(os.path.basename(path))
    if not m:
        return None
    base = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
    return base + int(m.group(3)) / 1e6


def ordered_frames(frames_dir):
    paths = [p for p in glob.glob(os.path.join(frames_dir, "*"))
             if p.lower().endswith(EXTS)]
    stamped = [(timestamp(p), p) for p in paths]
    if all(t is not None for t, _ in stamped):
        stamped.sort(key=lambda x: x[0])
    else:                                    # no usable timestamps -> filename order
        stamped = [(None, p) for p in sorted(paths)]
    return stamped


def split_bursts(stamped):
    """Group frames into continuous takes using the gaps between timestamps."""
    times = [t for t, _ in stamped if t is not None]
    if len(times) < 3:
        return [stamped], None
    deltas = [b - a for a, b in zip(times, times[1:])]
    median = statistics.median(deltas)
    if median <= 0:
        return [stamped], None

    bursts, current = [], [stamped[0]]
    for delta, item in zip(deltas, stamped[1:]):
        if delta > median * BURST_FACTOR:
            bursts.append(current)
            current = [item]
        else:
            current.append(item)
    bursts.append(current)
    return bursts, 1.0 / median


def write_video(items, out_path, fps):
    first = cv2.imread(items[0][1])
    if first is None:
        raise SystemExit(f"cannot read {items[0][1]}")
    h, w = first.shape[:2]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        raise SystemExit(f"VideoWriter failed to open {out_path}")
    for _, path in items:
        frame = cv2.imread(path)
        if frame is None:
            continue
        if frame.shape[:2] != (h, w):
            frame = cv2.resize(frame, (w, h))
        writer.write(frame)
    writer.release()
    return len(items), (w, h)


def build(frames_dir, out_dir, fps=None, whole=False, min_frames=5):
    stamped = ordered_frames(frames_dir)
    if not stamped:
        raise SystemExit(f"no images under {frames_dir}")

    bursts, native_fps = split_bursts(stamped)
    if whole:
        bursts = [stamped]
    rate = fps or native_fps or 10.0

    name = os.path.basename(frames_dir.rstrip(os.sep)) or "clip"
    out_dir = os.path.join(out_dir, name)
    made = []
    for i, burst in enumerate(bursts):
        if len(burst) < min_frames:
            continue
        out_path = os.path.join(out_dir, f"{name}_burst{i:02d}.mp4")
        n, (w, h) = write_video(burst, out_path, rate)
        print(f"  {out_path}  {n} frames  {w}x{h}  {rate:.2f} fps  {n/rate:.1f}s")
        made.append(out_path)

    print(f"\n{len(made)} clip(s) from {len(stamped)} frames "
          f"(native {native_fps:.2f} fps)" if native_fps else f"\n{len(made)} clip(s)")
    return made


def detect(weights, video_path, out_dir, conf=0.05, imgsz=1280, show_empty=True):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    out_video = os.path.join(out_dir, f"{stem}_tagged.mp4")
    out_csv = os.path.join(out_dir, f"{stem}_tags.csv")
    writer = cv2.VideoWriter(out_video, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    model = YOLO(weights)
    n_frames = n_hit = total_boxes = 0
    with open(out_csv, "w", newline="") as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(["frame", "t_sec", "has_item", "n_boxes", "max_conf", "boxes_xyxy"])
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            result = model.predict(frame, conf=conf, imgsz=imgsz, verbose=False)[0]
            boxes = result.boxes
            n = len(boxes)
            confs = [float(c) for c in boxes.conf]
            n_hit += n > 0
            total_boxes += n

            vis = result.plot() if (n or show_empty) else frame
            cv2.putText(vis, f"{stem}  f{n_frames:04d}  item={n}",
                        (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            writer.write(vis)

            csv_writer.writerow([n_frames, round(n_frames / fps, 3), int(n > 0), n,
                                 round(max(confs), 3) if confs else 0.0,
                                 [[round(float(v)) for v in b] for b in boxes.xyxy]])
            n_frames += 1

    cap.release()
    writer.release()
    print(f"{stem}: {n_hit}/{n_frames} frames with item, {total_boxes} boxes total")
    print(f"  -> {out_video}")
    return out_video, n_hit, n_frames


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="frames -> mp4")
    b.add_argument("--frames", required=True)
    b.add_argument("--out", default=os.path.join(REPO, "runs", "video"))
    b.add_argument("--fps", type=float, default=None, help="override the recovered rate")
    b.add_argument("--whole", action="store_true", help="one clip instead of per-burst")
    b.add_argument("--min-frames", type=int, default=5)

    d = sub.add_parser("detect", help="run the detector on a video")
    d.add_argument("--video", required=True, help="file or directory of mp4s")
    d.add_argument("--weights", default=os.path.join(REPO, "src", "runs", "detect",
                                                     "item", "weights", "best.pt"))
    d.add_argument("--out", default=os.path.join(REPO, "runs", "video_tagged"))
    d.add_argument("--conf", type=float, default=0.05)
    d.add_argument("--imgsz", type=int, default=1280)
    args = parser.parse_args()

    if args.cmd == "build":
        build(args.frames, args.out, args.fps, args.whole, args.min_frames)
    else:
        videos = ([args.video] if os.path.isfile(args.video)
                  else sorted(glob.glob(os.path.join(args.video, "**", "*.mp4"), recursive=True)))
        if not videos:
            raise SystemExit(f"no videos at {args.video}")
        hits = frames = 0
        for v in videos:
            _, nh, nf = detect(args.weights, v, args.out, args.conf, args.imgsz)
            hits += nh
            frames += nf
        if len(videos) > 1:
            print(f"\ntotal: {hits}/{frames} frames with item across {len(videos)} clips")
