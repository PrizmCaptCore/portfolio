"""Build a two-class (normal / abnormal) NanoDet dataset from the 5-class source.

Two things this does that a straight class-remap would not.

**It throws away Roboflow's split.** Roboflow re-exports one source photo as several
augmented files that differ only in a `.rf.<hash>` suffix, and scatters them across
train/valid/test. Measured on the crop dataset that came out of the same source, 23.6% of
valid and 16.8% of test shared a source photo with train -- so validation was scoring the
model on pictures it had trained on, and every number that came off it was inflated. Here
the split is drawn over *source photos*, so every augmented sibling lands together and a
validation score means something.

**It splits stratified on what the image contains.** After the remap an image is
normal-only, abnormal-only, or mixed. Splitting blind would let those drift apart between
train and valid; stratifying on the signature keeps the three proportions steady.

The remap itself is the easy part: source class 3 ('Item') is the healthy one, so it
becomes 0 (normal) and the four defect classes collapse into 1 (abnormal).

    python prepare_nanodet_binary.py
    python prepare_nanodet_binary.py --ratio 0.8 0.1 0.1 --seed 0

Images are symlinked (the source is ~1 GB and nothing here modifies it); labels are
written fresh because their class ids change.
"""
import os
import re
import glob
import random
import shutil
import argparse
import collections

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "item_extern_dataset", "item_downloads",
                   "Item_detection.v11i.yolov11")
DST = os.path.join(REPO, "datasets", "item_binary_nanodet")

# data.yaml order: ['Damaged item', 'Defected item', 'Diseased-fungal item',
#                   'Item', 'Sprouted item']
NORMAL_ID = 3
CLASS_NAMES = ["normal", "abnormal"]

# Roboflow renames every file to "<source stem>.rf.<hash>.<ext>". Strip the suffix and
# augmented copies of one photo collapse to a single identity.
RF_HASH = re.compile(r"\.rf\.[0-9a-f]+.*$")


def source_photo(path):
    return RF_HASH.sub("", os.path.splitext(os.path.basename(path))[0])


def remap(lbl_path):
    """YOLO label lines with class ids collapsed to 0/1. Returns None if unreadable."""
    out = []
    try:
        with open(lbl_path) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 5:
                    continue
                cid = 0 if int(parts[0]) == NORMAL_ID else 1
                out.append(" ".join([str(cid)] + parts[1:]))
    except OSError:
        return None
    return out


def collect():
    """Every image in the source, whatever split Roboflow filed it under, grouped by the
    photo it came from. The group is the unit that gets split -- that is the whole point."""
    groups = collections.defaultdict(list)
    for mode in ("train", "valid", "test"):
        for img in sorted(glob.glob(os.path.join(SRC, mode, "images", "*"))):
            stem = os.path.splitext(os.path.basename(img))[0]
            lbl = os.path.join(SRC, mode, "labels", stem + ".txt")
            if not os.path.isfile(lbl):
                continue
            lines = remap(lbl)
            if lines is None:
                continue
            groups[source_photo(img)].append((img, lines))
    return groups


def signature(items):
    """normal-only / abnormal-only / mixed, over every box in every copy of the photo."""
    ids = {ln.split()[0] for _, lines in items for ln in lines}
    if ids == {"0"}:
        return "normal"
    if ids == {"1"}:
        return "abnormal"
    return "mixed" if ids else "empty"


def split(groups, ratio, seed):
    by_sig = collections.defaultdict(list)
    for name, items in groups.items():
        by_sig[signature(items)].append(name)

    rng = random.Random(seed)
    out = {"train": [], "valid": [], "test": []}
    for sig, names in sorted(by_sig.items()):
        rng.shuffle(names)
        n = len(names)
        a, b = int(n * ratio[0]), int(n * (ratio[0] + ratio[1]))
        for mode, chunk in (("train", names[:a]), ("valid", names[a:b]), ("test", names[b:])):
            out[mode] += [(sig, g) for g in chunk]
    return out


def write(groups, assignment, dst):
    stats = {}
    for mode, entries in assignment.items():
        out_dir = os.path.join(dst, mode)
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir)

        n_img = 0
        boxes = collections.Counter()
        sigs = collections.Counter()
        for sig, group in entries:
            sigs[sig] += 1
            for img, lines in groups[group]:
                stem, ext = os.path.splitext(os.path.basename(img))
                link = os.path.join(out_dir, stem + ext)
                if not os.path.lexists(link):
                    os.symlink(os.path.abspath(img), link)
                with open(os.path.join(out_dir, stem + ".txt"), "w") as f:
                    f.write("\n".join(lines) + ("\n" if lines else ""))
                n_img += 1
                for ln in lines:
                    boxes[CLASS_NAMES[int(ln.split()[0])]] += 1
        stats[mode] = {"photos": len(entries), "images": n_img,
                       "boxes": dict(boxes), "signatures": dict(sigs)}
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=SRC)
    p.add_argument("--dst", default=DST)
    p.add_argument("--ratio", type=float, nargs=3, default=[0.8, 0.1, 0.1])
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    groups = collect()
    print(f"source: {sum(len(v) for v in groups.values())} images "
          f"from {len(groups)} distinct photos "
          f"({sum(len(v) for v in groups.values()) / max(len(groups), 1):.1f}x augmentation)")

    assignment = split(groups, args.ratio, args.seed)
    stats = write(groups, assignment, args.dst)

    print(f"\n{'':<8}{'photos':>8}{'images':>8}{'normal':>9}{'abnormal':>10}   signatures")
    for mode in ("train", "valid", "test"):
        s = stats[mode]
        print(f"  {mode:<6}{s['photos']:>8}{s['images']:>8}"
              f"{s['boxes'].get('normal', 0):>9}{s['boxes'].get('abnormal', 0):>10}"
              f"   {s['signatures']}")

    # The split is only worth anything if it actually holds, so check rather than assert
    # it in a docstring.
    sets = {m: {g for _, g in assignment[m]} for m in assignment}
    leaks = [(a, b, len(sets[a] & sets[b]))
             for a, b in (("train", "valid"), ("train", "test"), ("valid", "test"))]
    print("\n  " + "  ".join(f"{a}∩{b}={n}" for a, b, n in leaks)
          + ("   누수 없음" if all(n == 0 for *_, n in leaks) else "   <<< 누수!"))
    print(f"\n-> {args.dst}")


if __name__ == "__main__":
    main()
