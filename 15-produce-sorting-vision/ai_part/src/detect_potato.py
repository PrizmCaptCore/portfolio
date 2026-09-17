"""Stage 1 only: run the trained NanoDet potato detector and look at what it found.

Separated from pipeline.py so detection can be checked on its own, without the defect
classifier in the way. pipeline.py imports Detector from here, so there is one copy of the
inference path and the two cannot drift apart.

Set the SOURCE/SAVE/... constants below and run `python detect_potato.py`. This is a
scratch script for eyeballing detections, so the settings live in the file rather than
behind flags -- typical uses:

    # a folder of images, boxes written next to each other
    SOURCE = "../datasets/potato/test/images";  SAVE = "../runs/detect_check"

    # a video
    SOURCE = "../runs/video/SB/SB_burst00.mp4";  SAVE = "out.mp4"

    # webcam
    SOURCE = "0";  SHOW = True

To reproduce the mAP numbers in runs/nanodet_potato/model_best/eval_results.txt, use
nanodet's own evaluator rather than this script -- reimplementing COCO eval here would only
risk disagreeing with the numbers the model was selected on:

    cd <nanodet checkout> && python tools/test.py --task val \\
        --config <this repo>/ai_part/src/config/nanodet-plus-m-1.5x_416_potato.yml \\
        --model <this repo>/ai_part/runs/nanodet_potato/model_best/model_best.ckpt
"""
import io
import os
import time
import glob
import types
import contextlib

import cv2
import torch

from nanodet.data.batch_process import stack_batch_img
from nanodet.data.collate import naive_collate
from nanodet.data.transform import Pipeline
from nanodet.model.arch import build_model
from nanodet.util import Logger, cfg, load_config, load_model_weight

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_CFG = os.path.join(REPO, "src", "config", "nanodet-plus-m-1.5x_416_potato.yml")
DEF_DET = os.path.join(REPO, "runs", "nanodet_potato", "model_best", "nanodet_model_best.pth")

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv")


class Detector:
    """Wraps NanoDet inference and returns plain (x1, y1, x2, y2, score) tuples."""

    def __init__(self, config, weights, device):
        load_config(cfg, config)
        self.cfg = cfg
        self.device = device
        model = build_model(cfg.model)
        load_model_weight(model, torch.load(weights, map_location="cpu"),
                          Logger(0, use_tensorboard=False))
        self.model = model.to(device).eval()
        self.pipeline = Pipeline(cfg.data.val.pipeline, cfg.data.val.keep_ratio)

    @torch.no_grad()
    def __call__(self, frame, score_thr, with_class=False):
        h, w = frame.shape[:2]
        meta = dict(img_info={"id": 0, "height": h, "width": w, "file_name": None},
                    raw_img=frame, img=frame)
        meta = self.pipeline(None, meta, self.cfg.data.val.input_size)
        meta["img"] = torch.from_numpy(meta["img"].transpose(2, 0, 1)).to(self.device)
        meta = naive_collate([meta])
        meta["img"] = stack_batch_img(meta["img"], divisible=32)
        # nanodet's inference() prints per-frame timings straight to stdout, which buries
        # whatever the caller is actually trying to read.
        with contextlib.redirect_stdout(io.StringIO()):
            res = self.model.inference(meta)

        # with_class keeps the class id on each box. Off by default so the callers that
        # only ever ask "where are the potatoes" (pipeline.py, export_tracks.py) keep the
        # 5-tuple they unpack; on for the two-class model, where the class *is* the answer.
        boxes = []
        for cid, dets in res[0].items():
            for x1, y1, x2, y2, s in dets:
                if s >= score_thr:
                    boxes.append((x1, y1, x2, y2, s, cid) if with_class
                                 else (x1, y1, x2, y2, s))
        return boxes


def draw(frame, boxes):
    for x1, y1, x2, y2, s in boxes:
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
        cv2.putText(frame, f"{s:.2f}", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 2)
    cv2.putText(frame, f"potatoes: {len(boxes)}", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
    return frame


def run_images(detector, paths, args):
    if args.save:
        os.makedirs(args.save, exist_ok=True)

    total, times = 0, []
    for i, path in enumerate(paths):
        frame = cv2.imread(path)
        if frame is None:
            continue
        t0 = time.time()
        boxes = detector(frame, args.det_thr)
        times.append((time.time() - t0) * 1000)
        total += len(boxes)
        print(f"{os.path.basename(path):<40} {len(boxes):>3} potatoes", flush=True)

        if args.save or args.show:
            out = draw(frame, boxes)
            if args.save:
                cv2.imwrite(os.path.join(args.save, os.path.basename(path)), out)
            if args.show:
                cv2.imshow("detect", out)
                if cv2.waitKey(0) & 0xFF in (27, ord("q")):
                    break

    warm = times[args.warmup:] or times
    print(f"\n{len(times)} images, {total} potatoes "
          f"({total / max(len(times), 1):.1f} per image)")
    print(f"  detect {sum(warm) / len(warm):.1f} ms/image")


def run_video(detector, source, args):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"cannot open source: {source}")

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

    times, total, n = [], 0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t0 = time.time()
        boxes = detector(frame, args.det_thr)
        times.append((time.time() - t0) * 1000)
        total += len(boxes)
        n += 1

        if writer or args.show:
            out = draw(frame, boxes)
            if writer:
                writer.write(out)
            if args.show:
                cv2.imshow("detect", out)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break

    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()

    # The first frames pay for lazy CUDA init and cudnn.benchmark autotuning; averaging them
    # in makes the number meaningless on the short burst clips.
    warm = times[args.warmup:] or times
    print(f"\n{n} frames, {total} detections ({total / max(n, 1):.1f} per frame)")
    print(f"  detect {sum(warm) / len(warm):.1f} ms/frame "
          f"({1000 / (sum(warm) / len(warm)):.1f} fps detector-only)")


# Edit these and run the file -- no CLI. run_images()/run_video() read them off `args`.
SOURCE = os.path.join(REPO, "runs", "video", "SB")  # image, folder, video, or "0" for webcam
CONFIG = DEF_CFG
WEIGHTS = DEF_DET
DET_THR = 0.20
LIMIT = 0            # cap image/clip count (0 = all)
WARMUP = 5           # frames excluded from the timing average
SAVE   = os.path.join(REPO, "runs", "detect_check", "SB")          # folder (images, or a folder of clips) or .mp4 (single video); None = don't write
SHOW = False


def main():
    args = types.SimpleNamespace(source=SOURCE, config=CONFIG, weights=WEIGHTS,
                                 det_thr=DET_THR, limit=LIMIT, warmup=WARMUP,
                                 save=SAVE, show=SHOW)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.backends.cudnn.benchmark = True
    detector = Detector(args.config, args.weights, device)
    print(f"device {device}  weights {args.weights}")

    src = args.source
    if src.isdigit():
        run_video(detector, int(src), args)
    elif os.path.isdir(src):
        listing = sorted(glob.glob(os.path.join(src, "*")))
        images = [f for f in listing if f.lower().endswith(IMAGE_EXT)]
        videos = [f for f in listing if f.lower().endswith(VIDEO_EXT)]
        if args.limit:
            images, videos = images[:args.limit], videos[:args.limit]
        if images:
            run_images(detector, images, args)
        elif videos:
            # A folder of clips (runs/video/SB): each is its own run with its own timing
            # line -- one average across clips of different lengths would hide the slow one.
            # SAVE is the output *folder* here, not a single .mp4.
            for path in videos:
                print(f"\n=== {os.path.basename(path)}")
                clip = types.SimpleNamespace(**vars(args))
                if args.save:
                    clip.save = os.path.join(args.save, os.path.basename(path))
                run_video(detector, path, clip)
        else:
            raise SystemExit(f"no images or videos in {src}")
    elif src.lower().endswith(VIDEO_EXT):
        run_video(detector, src, args)
    else:
        run_images(detector, [src], args)


if __name__ == "__main__":
    main()
