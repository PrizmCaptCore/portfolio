"""Merge the external Roboflow datasets into one single-class ("potato") YOLO dataset.

The in-house rig images under potato_img/ are deliberately NOT touched here -- they are
held out as the test set. This builds train/valid/test purely from potato_extern_dataset/.

Two things the source datasets do that need handling:
  * class names vary wildly -- 'potato', 'Potatoes', 'Potato', and literal '0'
  * the same source photo is re-exported across datasets with different augmentation,
    so a naive merge leaks the same image into both train and valid
"""
import os
import re
import glob
import shutil
import hashlib
import argparse
from collections import Counter

import yaml

MODES = ("train", "valid", "test")

# Roboflow renames every file to "<source stem>_<ext>.rf.<hash>.<ext>".
# Recovering the source stem is what lets us spot re-exports of the same photo.
RF_SUFFIX = re.compile(r"\.rf\.[0-9a-f]+$")

DEFECT_WORDS = ("damaged", "defected", "diseased", "sprouted", "rotten", "fungal")


def source_stem(filename):
    """'99_jpg.rf.c1297d....jpg' -> '99_jpg'  (identifies the pre-augmentation photo)."""
    stem = os.path.splitext(filename)[0]
    return RF_SUFFIX.sub("", stem)


class PotatoDataset():
    def __init__(self, root_paths, output_path, include_defective=True, keep_negatives=True):
        self.root_paths = root_paths
        self.output_path = output_path
        self.include_defective = include_defective
        self.keep_negatives = keep_negatives
        self.stats = Counter()

        if os.path.isdir(self.output_path):
            shutil.rmtree(self.output_path)
        for mode in MODES:
            os.makedirs(os.path.join(self.output_path, mode, "images"))
            os.makedirs(os.path.join(self.output_path, mode, "labels"))

    def potato_ids(self, root_path):
        """Class indices in this dataset that count as 'potato'."""
        yaml_path = glob.glob(os.path.join(root_path, "*.yaml"))[0]
        with open(yaml_path, "r") as f:
            classes = yaml.safe_load(f)["names"]
        if isinstance(classes, dict):                       # {0: 'potato', ...} form
            classes = [classes[k] for k in sorted(classes)]

        # Single-class datasets sometimes name the class '0'. Whatever it is called,
        # if there is only one class in a potato dataset it is the potato.
        if len(classes) == 1:
            return {0}

        ids = set()
        for i, name in enumerate(classes):
            low = name.lower()
            if "potato" not in low:
                continue
            if not self.include_defective and any(w in low for w in DEFECT_WORDS):
                continue
            ids.add(i)
        return ids

    def read_boxes(self, label_path, potato_ids):
        """Return YOLO '0 cx cy w h' lines for the potato objects in this label file."""
        lines = []
        with open(label_path, "r") as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                if int(float(parts[0])) not in potato_ids:
                    continue
                coords = [float(v) for v in parts[1:]]
                if len(coords) > 4:                          # polygon -> enclosing box
                    xs, ys = coords[0::2], coords[1::2]
                    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                    coords = [(x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0]
                elif len(coords) < 4:
                    continue
                cx, cy, w, h = (min(max(v, 0.0), 1.0) for v in coords[:4])
                if w <= 0 or h <= 0:
                    continue
                lines.append(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
        return lines

    def find_image(self, label_path):
        """Locate the image next to a label file, whatever its extension."""
        images_dir = os.path.join(os.path.dirname(os.path.dirname(label_path)), "images")
        stem = os.path.splitext(os.path.basename(label_path))[0]
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".JPG", ".PNG"):
            candidate = os.path.join(images_dir, stem + ext)
            if os.path.isfile(candidate):
                return candidate
        return None

    def collect(self):
        """Gather every (image, boxes, mode) triple across all source datasets."""
        records = []
        for root_path in self.root_paths:
            potato_ids = self.potato_ids(root_path)
            name = os.path.basename(root_path.rstrip(os.sep))
            kept = 0
            for mode in MODES:
                for label_path in glob.glob(os.path.join(root_path, mode, "labels", "*.txt")):
                    image_path = self.find_image(label_path)
                    if image_path is None:
                        self.stats["missing_image"] += 1
                        continue
                    boxes = self.read_boxes(label_path, potato_ids)
                    if not boxes and not self.keep_negatives:
                        self.stats["dropped_negative"] += 1
                        continue
                    records.append({"image": image_path, "boxes": boxes, "mode": mode,
                                    "stem": source_stem(os.path.basename(image_path))})
                    kept += 1
            print(f"  {name}: potato class ids {sorted(potato_ids)} -> {kept} images")
        return records

    def build_dataset(self):
        print("Collecting source datasets...")
        records = self.collect()

        # Pin every re-export of a source photo to one split, otherwise the same
        # image (augmented differently) shows up in train and valid at once.
        split_of_stem = {}
        for rec in sorted(records, key=lambda r: MODES.index(r["mode"])):
            split_of_stem.setdefault(rec["stem"], rec["mode"])

        seen_hashes = set()
        counts = Counter()
        for rec in records:
            with open(rec["image"], "rb") as f:
                digest = hashlib.md5(f.read()).hexdigest()
            if digest in seen_hashes:                        # byte-identical re-export
                self.stats["dropped_duplicate"] += 1
                continue
            seen_hashes.add(digest)

            mode = split_of_stem[rec["stem"]]
            if mode != rec["mode"]:
                self.stats["moved_to_avoid_leakage"] += 1

            idx = counts[mode]
            counts[mode] += 1
            ext = os.path.splitext(rec["image"])[1].lower()
            shutil.copyfile(rec["image"],
                            os.path.join(self.output_path, mode, "images", f"{idx}{ext}"))
            with open(os.path.join(self.output_path, mode, "labels", f"{idx}.txt"), "w") as f:
                f.write("\n".join(rec["boxes"]) + ("\n" if rec["boxes"] else ""))

            self.stats["negatives" if not rec["boxes"] else "positives"] += 1
            self.stats["boxes"] += len(rec["boxes"])

        print("\nSplit sizes:", dict(counts))
        print("Stats:", dict(self.stats))
        return counts

    def create_yaml(self):
        """Paths are relative to `path`, so the dataset folder stays movable."""
        yaml_path = os.path.join(self.output_path, "data.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump({
                "path": os.path.abspath(self.output_path),
                "train": "train/images",
                "val": "valid/images",
                "test": "test/images",
                "nc": 1,
                "names": ["potato"],
            }, f, sort_keys=False)
        print("Wrote", yaml_path)
        return yaml_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)

    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=os.path.join(repo, "potato_extern_dataset", "potato_downloads"))
    parser.add_argument("--out", default=os.path.join(repo, "datasets", "potato"))
    parser.add_argument("--no-defective", action="store_true",
                        help="treat damaged/diseased/sprouted potatoes as non-potato")
    parser.add_argument("--no-negatives", action="store_true",
                        help="drop images with no potato instead of keeping them as background")
    args = parser.parse_args()

    root_paths = sorted(d for d in glob.glob(os.path.join(args.src, "*")) if os.path.isdir(d))
    if not root_paths:
        raise SystemExit(f"no dataset folders under {args.src}")

    dataset = PotatoDataset(root_paths, args.out,
                            include_defective=not args.no_defective,
                            keep_negatives=not args.no_negatives)
    dataset.build_dataset()
    dataset.create_yaml()
