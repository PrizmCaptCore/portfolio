"""Re-lay out datasets/potato for NanoDet's YoloDataset.

Ultralytics keeps images and labels in sibling images/ and labels/ folders. NanoDet's
YoloDataset instead looks for the image next to the .txt, same stem, same directory, so
the two layouts are incompatible even though the label format is identical.

Symlinks rather than copies -- the dataset is ~1 GB and nothing here modifies it.

    python prepare_nanodet_data.py
"""
import os
import glob
import shutil
import argparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ("train", "valid", "test")


def build(src, dst, use_symlink=True):
    counts = {}
    for mode in MODES:
        img_dir = os.path.join(src, mode, "images")
        lbl_dir = os.path.join(src, mode, "labels")
        if not os.path.isdir(img_dir):
            continue

        out = os.path.join(dst, mode)
        if os.path.isdir(out):
            shutil.rmtree(out)
        os.makedirs(out)

        n = n_empty = 0
        for img in sorted(glob.glob(os.path.join(img_dir, "*"))):
            stem, ext = os.path.splitext(os.path.basename(img))
            lbl = os.path.join(lbl_dir, stem + ".txt")
            if not os.path.isfile(lbl):
                continue

            for src_file, name in ((img, stem + ext), (lbl, stem + ".txt")):
                target = os.path.join(out, name)
                if use_symlink:
                    os.symlink(os.path.abspath(src_file), target)
                else:
                    shutil.copyfile(src_file, target)

            n += 1
            n_empty += os.path.getsize(lbl) == 0

        counts[mode] = (n, n_empty)
        print(f"  {mode:<6} {n:>6} images  ({n_empty} background / no boxes)")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=os.path.join(REPO, "datasets", "potato"))
    parser.add_argument("--dst", default=os.path.join(REPO, "datasets", "potato_nanodet"))
    parser.add_argument("--copy", action="store_true", help="copy instead of symlink")
    args = parser.parse_args()

    print(f"{args.src}  ->  {args.dst}")
    build(args.src, args.dst, use_symlink=not args.copy)
    print("\ndone")
