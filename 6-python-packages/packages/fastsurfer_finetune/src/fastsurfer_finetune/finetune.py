"""Step 3b: fine-tune one FastSurferCNN v1 plane network from the released Epoch_30 checkpoint.

Why fine-tune instead of retrain: the released weights come from ~140 subjects across public cohorts; our
disagreement set is a few dozen subjects from scanners those cohorts under-represent. Retraining from
scratch on that would overfit; fine-tuning with a small LR and the encoder frozen for the first epochs
moves only the decision boundary. Concretely, in v1 terms:

  * model = FastSurferCNN(params_network) with the stock params (64 filters, 5x5 kernels, 7 channels)
  * weights from checkpoints/{Plane}_Weights_FastSurferCNN/ckpts/Epoch_30_training_state.pkl
    ("model_state_dict", possibly with a "module." DataParallel prefix -- handled like eval.py does)
  * phase 1 (freeze_epochs): encode1..4 + bottleneck frozen, decoders + classifier at lr
  * phase 2: everything at lr / 5
  * data = AsegDatasetWithAugmentation over our HDF5, with train.py's augmentations (pad 8 + random crop)
  * loss = CombinedLoss (weighted CE + Dice), returns (total, dice, ce) like Solver uses it
  * early stop on val mean Dice of the subcortical classes, not on loss -- loss keeps falling on white
    matter long after the small structures stop improving
  * checkpoint saved as Epoch_NN_training_state.pkl with the same keys Solver writes, so eval.py can take
    --network_{plane}_path pointing at it with no code change

v1 has no config system; everything is a dict, mirrored here in FinetuneConfig.
"""
from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import torch
import yaml
from torch.utils.data import DataLoader
from torchvision import transforms

from .labels import fastsurfer_home, num_classes, subcortical_class_indices


@dataclass
class FinetuneConfig:
    plane: str = "coronal"
    ckpt_in: str = "checkpoints/Coronal_Weights_FastSurferCNN/ckpts/Epoch_30_training_state.pkl"
    out_dir: str = "runs/finetune/coronal"
    epochs: int = 12
    freeze_epochs: int = 3
    lr: float = 1e-4            # stock training used 1e-2 from scratch; two orders lower for fine-tuning
    batch_size: int = 16
    num_filters: int = 64
    kernel: int = 5
    seed: int = 1


def network_params(cfg: FinetuneConfig) -> Dict[str, int]:
    """Exactly the dict train.py / eval.py build; sub_module.py reads these keys."""
    return {"num_channels": 7, "num_filters": cfg.num_filters,
            "kernel_h": cfg.kernel, "kernel_w": cfg.kernel, "stride_conv": 1,
            "pool": 2, "stride_pool": 2, "num_classes": num_classes(cfg.plane),
            "kernel_c": 1, "kernel_d": 1, "batch_size": cfg.batch_size, "height": 256, "width": 256}


def load_v1_checkpoint(model: torch.nn.Module, path: str, device: torch.device) -> None:
    state = torch.load(path, map_location=device)["model_state_dict"]
    fixed = OrderedDict((k[7:] if k.startswith("module.") else k, v) for k, v in state.items())
    model.load_state_dict(fixed, strict=True)  # a mismatch means wrong plane / class count; fail loudly


def set_encoder_frozen(model: torch.nn.Module, frozen: bool) -> None:
    for name, p in model.named_parameters():
        if name.startswith(("encode1", "encode2", "encode3", "encode4", "bottleneck")):
            p.requires_grad = not frozen


def mean_dice(pred: torch.Tensor, lab: torch.Tensor, classes) -> float:
    ds = []
    for c in classes:
        a, b = pred == c, lab == c
        denom = a.sum() + b.sum()
        if denom > 0:
            ds.append((2.0 * (a & b).sum() / denom).item())
    return float(np.mean(ds)) if ds else 0.0


def run(cfg: FinetuneConfig, train_h5: str, val_h5: str) -> Dict[str, float]:
    fastsurfer_home()
    from data_loader.augmentation import AugmentationPadImage, AugmentationRandomCrop, ToTensor  # type: ignore
    from data_loader.load_neuroimaging_data import AsegDatasetWithAugmentation  # type: ignore
    from models.losses import CombinedLoss  # type: ignore
    from models.networks import FastSurferCNN  # type: ignore

    torch.manual_seed(cfg.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = FastSurferCNN(network_params(cfg)).to(device)
    load_v1_checkpoint(model, cfg.ckpt_in, device)
    criterion = CombinedLoss()

    tf_train = transforms.Compose([AugmentationPadImage(pad_size=8),
                                   AugmentationRandomCrop(output_size=(256, 256)), ToTensor()])
    tf_val = transforms.Compose([ToTensor()])
    train_dl = DataLoader(AsegDatasetWithAugmentation({"dataset_name": train_h5, "plane": cfg.plane}, tf_train),
                          batch_size=cfg.batch_size, shuffle=True, drop_last=True)
    val_dl = DataLoader(AsegDatasetWithAugmentation({"dataset_name": val_h5, "plane": cfg.plane}, tf_val),
                        batch_size=cfg.batch_size)

    subcort = subcortical_class_indices(cfg.plane)
    os.makedirs(cfg.out_dir, exist_ok=True)
    best, history = -1.0, {}
    for epoch in range(cfg.epochs):
        frozen = epoch < cfg.freeze_epochs
        set_encoder_frozen(model, frozen)
        lr = cfg.lr if frozen else cfg.lr / 5
        # same optimizer family/args as train.py's adam branch, restricted to trainable params
        opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad],
                               lr=lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=1e-4)

        model.train()
        t0, run_loss = time.time(), 0.0
        for batch in train_dl:
            img = batch["image"].to(device)
            lab = batch["label"].to(device)
            w = batch["weight"].to(device).float()
            loss, _dice, _ce = criterion(model(img), lab, w)
            opt.zero_grad()
            loss.backward()
            opt.step()
            run_loss += loss.item()

        model.eval()
        dices = []
        with torch.no_grad():
            for batch in val_dl:
                pred = model(batch["image"].to(device)).argmax(1)
                dices.append(mean_dice(pred, batch["label"].to(device), subcort))
        val_dice = float(np.mean(dices))
        history[f"epoch{epoch}"] = val_dice
        print(f"epoch {epoch:02d} {'frozen' if frozen else 'full  '} lr={lr:.1e} "
              f"loss={run_loss / max(1, len(train_dl)):.4f} val_subcort_dice={val_dice:.4f} ({time.time() - t0:.0f}s)")

        if val_dice > best:
            best = val_dice
            # Solver's layout: eval.py reads "model_state_dict"; keep the Epoch_NN name so tooling that globs it works
            torch.save({"model_state_dict": model.state_dict(), "optimizer_state_dict": opt.state_dict(),
                        "epoch": epoch, "plane": cfg.plane, "val_subcortical_dice": best,
                        "finetuned_from": cfg.ckpt_in},
                       os.path.join(cfg.out_dir, f"Epoch_{epoch:02d}_training_state.pkl"))
            torch.save({"model_state_dict": model.state_dict()}, os.path.join(cfg.out_dir, "best_training_state.pkl"))
    history["best"] = best
    return history


def load_config(path: Optional[str]) -> FinetuneConfig:
    if not path:
        return FinetuneConfig()
    with open(path, encoding="utf-8") as f:
        return FinetuneConfig(**yaml.safe_load(f))
