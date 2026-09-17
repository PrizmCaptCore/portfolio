"""Tag potatoes in the in-house rig images -- no counting, no tracking.

Each image is classified as potato / no-potato by whether anything was detected,
and every detection is drawn as a box. Results are written to a CSV so the
has-potato decision can be checked against the internal_IMG / background split.
"""
import os
import csv
import argparse

import cv2
from ultralytics import YOLO

EXTS = (".png", ".jpg", ".jpeg", ".bmp")


def collect_images(source):
    if os.path.isfile(source):
        return [source]
    paths = []
    for dirpath, _, filenames in os.walk(source):
        for name in filenames:
            if name.lower().endswith(EXTS):
                paths.append(os.path.join(dirpath, name))
    return sorted(paths)


def tag(weights, source, out_dir, conf=0.25, imgsz=1280, save_images=True, limit=None):
    paths = collect_images(source)
    if limit:
        paths = paths[:limit]
    if not paths:
        raise SystemExit(f"no images under {source}")

    model = YOLO(weights)
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "tags.csv")

    n_potato = 0
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["image", "has_potato", "n_boxes", "max_conf", "boxes_xyxy"])

        for i in range(0, len(paths), 16):                   # batch to keep VRAM flat
            batch = paths[i:i + 16]
            for path, result in zip(batch, model.predict(batch, conf=conf, imgsz=imgsz,
                                                         verbose=False)):
                boxes = result.boxes
                n = len(boxes)
                n_potato += n > 0
                confs = [float(c) for c in boxes.conf]
                xyxy = [[round(float(v)) for v in b] for b in boxes.xyxy]
                writer.writerow([os.path.relpath(path, source) if os.path.isdir(source) else path,
                                 int(n > 0), n, round(max(confs), 3) if confs else 0.0, xyxy])

                if save_images and n:
                    rel = os.path.relpath(path, source) if os.path.isdir(source) else os.path.basename(path)
                    dst = os.path.join(out_dir, "tagged", rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    cv2.imwrite(os.path.splitext(dst)[0] + ".jpg", result.plot())

            print(f"  {min(i + 16, len(paths))}/{len(paths)}", end="\r")

    print(f"\n{n_potato}/{len(paths)} images tagged as containing potato")
    print("Wrote", csv_path)
    return csv_path


if __name__ == "__main__":
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser()
    #potato best weights: runs/detect/potato/weights/best.pt
    parser.add_argument("--weights", default=os.path.join(repo, "src","runs", "detect", "potato", "weights", "best.pt"))
    #potato images: potato_img/raw
    parser.add_argument("--source", default=os.path.join(repo, "potato_img", "raw"))
    parser.add_argument("--out", default=os.path.join(repo, "runs", "tag"))
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--no-save-images", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    tag(args.weights, args.source, args.out, args.conf, args.imgsz,
        save_images=not args.no_save_images, limit=args.limit)
