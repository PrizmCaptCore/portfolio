"""Step 3b: fine-tune one FastSurferCNN plane model from the released checkpoint.

Why fine-tune instead of retrain: the released checkpoints were trained on ~140 subjects across several
public cohorts; our disagreement set is a few dozen subjects from scanners those cohorts under-represent.
Retraining from scratch on that would overfit; fine-tuning with a small LR and the encoder frozen for the
first epochs moves only the decision boundary. Concretely:

  * start from the plane checkpoint (checkpoints/aparc_vinn_{plane}_v2.0.0.pkl)
  * phase 1 (freeze_epochs): encoder frozen, decoder + classifier at lr
  * phase 2: everything unfrozen at lr / 5
  * loss = FastSurfer's CombinedLoss (weighted CE + Dice) using the per-slice weight masks from dataset.py
  * early stop on val mean Dice of the subcortical classes, not on loss -- loss keeps falling on white matter
    long after the small structures stop improving
  * save in the same dict layout FastSurfer loads (model_state, plane, ...) so run_prediction.py can take
    --ckpt_{plane} pointing at the result with no code change
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict, Optional

import h5py
import numpy as np
import torch
import yaml
from torch.utils.data import DataLoader, Dataset

from .labels import fastsurfer_home


@dataclass
class FinetuneConfig:
    plane: str = "coronal"
    ckpt_in: str = "checkpoints/aparc_vinn_coronal_v2.0.0.pkl"
    ckpt_out: str = "runs/finetune/coronal_best.pkl"
    cfg_yaml: str = "FastSurferCNN/config/FastSurferVINN.yaml"
    epochs: int = 12
    freeze_epochs: int = 3
    lr: float = 1e-4
    batch_size: int = 16
    num_workers: int = 4
    amp: bool = True
    seed: int = 0


class SliceH5(Dataset):
    def __init__(self, path: str):
        self.path, self._f = path, None
        with h5py.File(path, "r") as f:
            self.n = f["orig_dataset"].shape[0]

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, i: int):
        if self._f is None:  # open lazily so DataLoader workers each get their own handle
            self._f = h5py.File(self.path, "r")
        img = torch.from_numpy(self._f["orig_dataset"][i]).permute(2, 0, 1).float() / 255.0  # (7,H,W)
        lab = torch.from_numpy(self._f["aseg_dataset"][i].astype(np.int64))
        w = torch.from_numpy(self._f["weight_dataset"][i])
        return {"image": img, "label": lab, "weight": w}


def build_model(cfg_yaml: str, plane: str, device: torch.device):
    fastsurfer_home()
    from FastSurferCNN.models.networks import build_model as fs_build  # type: ignore
    from FastSurferCNN.config.defaults import get_cfg_defaults  # type: ignore

    cfg = get_cfg_defaults()
    cfg.merge_from_file(cfg_yaml)
    cfg.DATA.PLANE = plane
    cfg.MODEL.NUM_CLASSES = 51 if plane == "sagittal" else 79
    return fs_build(cfg).to(device), cfg


def load_checkpoint(model: torch.nn.Module, path: str, device: torch.device) -> None:
    state = torch.load(path, map_location=device)
    state = state.get("model_state", state)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if unexpected:
        raise RuntimeError(f"checkpoint has keys the model does not: {unexpected[:5]}")
    if missing:
        print(f"[warn] {len(missing)} keys not in checkpoint (fresh init): {missing[:3]}")


def set_encoder_frozen(model: torch.nn.Module, frozen: bool) -> None:
    # FastSurferVINN names: encode1..encode4 + bottleneck are the encoder; decode*/classifier are trained.
    for name, p in model.named_parameters():
        if name.startswith(("encode", "bottleneck", "inp_block")):
            p.requires_grad = not frozen


def subcortical_dice(pred: torch.Tensor, lab: torch.Tensor, classes: range) -> float:
    ds = []
    for c in classes:
        a, b = pred == c, lab == c
        denom = a.sum() + b.sum()
        if denom > 0:
            ds.append((2.0 * (a & b).sum() / denom).item())
    return float(np.mean(ds)) if ds else 0.0


def run(cfg: FinetuneConfig, train_h5: str, val_h5: str) -> Dict[str, float]:
    torch.manual_seed(cfg.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, fs_cfg = build_model(cfg.cfg_yaml, cfg.plane, device)
    load_checkpoint(model, cfg.ckpt_in, device)

    from FastSurferCNN.models.losses import get_loss_func  # type: ignore
    fs_cfg.MODEL.LOSS_FUNC = "combined"  # weighted CE + Dice
    criterion = get_loss_func(fs_cfg)

    train_dl = DataLoader(SliceH5(train_h5), batch_size=cfg.batch_size, shuffle=True,
                          num_workers=cfg.num_workers, pin_memory=True, drop_last=True)
    val_dl = DataLoader(SliceH5(val_h5), batch_size=cfg.batch_size, num_workers=cfg.num_workers)

    scaler = torch.cuda.amp.GradScaler(enabled=cfg.amp and device.type == "cuda")
    subcort = range(1, 34)  # compact class indices of the aseg (non-cortical) labels in FastSurfer's order
    best, history = -1.0, {}
    for epoch in range(cfg.epochs):
        frozen = epoch < cfg.freeze_epochs
        set_encoder_frozen(model, frozen)
        lr = cfg.lr if frozen else cfg.lr / 5
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=1e-4)

        model.train()
        t0, run_loss = time.time(), 0.0
        for batch in train_dl:
            img, lab, w = (batch[k].to(device, non_blocking=True) for k in ("image", "label", "weight"))
            with torch.autocast(device_type=device.type, enabled=scaler.is_enabled()):
                logits = model(img)
                loss, _, _ = criterion(logits, lab, w)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            run_loss += loss.item()

        model.eval()
        dices = []
        with torch.no_grad():
            for batch in val_dl:
                img, lab = batch["image"].to(device), batch["label"].to(device)
                dices.append(subcortical_dice(model(img).argmax(1), lab, subcort))
        val_dice = float(np.mean(dices))
        history[f"epoch{epoch}"] = val_dice
        print(f"epoch {epoch:02d} {'frozen' if frozen else 'full  '} lr={lr:.1e} "
              f"loss={run_loss / len(train_dl):.4f} val_subcort_dice={val_dice:.4f} ({time.time() - t0:.0f}s)")

        if val_dice > best:
            best = val_dice
            os.makedirs(os.path.dirname(cfg.ckpt_out) or ".", exist_ok=True)
            torch.save({"model_state": model.state_dict(), "plane": cfg.plane, "epoch": epoch,
                        "val_subcortical_dice": best, "finetuned_from": cfg.ckpt_in}, cfg.ckpt_out)
    history["best"] = best
    return history


def load_config(path: Optional[str]) -> FinetuneConfig:
    if not path:
        return FinetuneConfig()
    with open(path, encoding="utf-8") as f:
        return FinetuneConfig(**yaml.safe_load(f))
