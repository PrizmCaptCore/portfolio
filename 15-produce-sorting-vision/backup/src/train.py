"""Train a single-class potato detector on the merged external datasets."""
import os
import argparse

from ultralytics import YOLO


def train(yaml_path, model="yolo11n.pt", epochs=100, imgsz=640, batch=16, name="potato"):
    yolo = YOLO(model)
    yolo.train(
        data=yaml_path,
        epochs=epochs,
        batch=batch,
        patience=20,
        lr0=1e-3,
        cos_lr=True,
        imgsz=imgsz,          # the source images are all 640x640; 1280 only upscales
        name=name,
        resume=False,
        save=True,
    )
    return yolo


if __name__ == "__main__":
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.path.join(repo, "datasets", "potato", "data.yaml"))
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--name", default="potato")
    args = parser.parse_args()

    train(args.data, args.model, args.epochs, args.imgsz, args.batch, args.name)
