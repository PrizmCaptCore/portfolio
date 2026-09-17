"""End-to-end: build the dataset, train, then tag the in-house rig images."""
import os
import argparse

from backup.src.dataset import ItemDataset
import glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(steps, epochs, conf, limit):
    data_yaml = os.path.join(REPO, "datasets", "item", "data.yaml")

    if "dataset" in steps:
        src = os.path.join(REPO, "item_extern_dataset", "item_downloads")
        root_paths = sorted(d for d in glob.glob(os.path.join(src, "*")) if os.path.isdir(d))
        builder = ItemDataset(root_paths, os.path.join(REPO, "datasets", "item"))
        builder.build_dataset()
        data_yaml = builder.create_yaml()

    if "train" in steps:
        from backup.src.train import train
        train(data_yaml, epochs=epochs)

    if "tag" in steps:
        from backup.src.tag import tag
        tag(weights=os.path.join(REPO, "runs", "detect", "item", "weights", "best.pt"),
            source=os.path.join(REPO, "item_img", "raw"),
            out_dir=os.path.join(REPO, "runs", "tag"),
            conf=conf, limit=limit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", nargs="+", default=["dataset", "train", "tag"],
                        choices=["dataset", "train", "tag"])
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=None, help="cap images during tagging")
    args = parser.parse_args()

    main(args.steps, args.epochs, args.conf, args.limit)
