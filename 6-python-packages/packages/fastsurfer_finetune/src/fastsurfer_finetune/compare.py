"""Step 1: score FastSurfer against FreeSurfer recon-all, per subject and per structure.

Both pipelines write into a FreeSurfer-style subject directory:

    <subjects_dir>/<subject>/mri/orig.mgz                       conformed T1 (256^3, 1 mm, LIA)
    <fastsurfer_dir>/<subject>/mri/aparc.DKTatlas+aseg.deep.mgz FastSurfer CNN output
    <freesurfer_dir>/<subject>/mri/aseg.mgz                     FreeSurfer recon-all (reference)

FreeSurfer is treated as the reference, not the truth: recon-all has its own failure modes (skull-strip
misses, topology fixes that eat hippocampus), so the comparison is a *disagreement detector*. A subject with
low agreement is a candidate for (a) manual QC and (b) the fine-tuning set, with FreeSurfer as the label
only after QC passes. Numbers per structure: Dice, absolute volume difference in %, and the 95th percentile
of the surface distance (HD95) in mm, which catches boundary drift that Dice hides on large structures.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import ndimage

from .labels import SUBCORTICAL

FASTSURFER_SEG = os.path.join("mri", "aparc.DKTatlas+aseg.deep.mgz")
FREESURFER_SEG = os.path.join("mri", "aseg.mgz")


@dataclass
class StructureScore:
    subject: str
    label: int
    name: str
    dice: float
    vol_fs_mm3: float
    vol_ref_mm3: float
    vol_diff_pct: float
    hd95_mm: float


def load_seg(path: str) -> np.ndarray:
    img = nib.load(path)
    if img.shape != (256, 256, 256):
        raise ValueError(f"{path}: expected conformed 256^3 volume, got {img.shape}")
    return np.asanyarray(img.dataobj).astype(np.int32)


def dice(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.count_nonzero(a & b)
    denom = np.count_nonzero(a) + np.count_nonzero(b)
    return 1.0 if denom == 0 else 2.0 * inter / denom


def hd95(a: np.ndarray, b: np.ndarray, spacing: float = 1.0) -> float:
    """95th-percentile symmetric surface distance. Returns nan if either mask is empty."""
    if not a.any() or not b.any():
        return float("nan")
    struct = ndimage.generate_binary_structure(3, 1)
    surf_a = a & ~ndimage.binary_erosion(a, struct)
    surf_b = b & ~ndimage.binary_erosion(b, struct)
    dt_a = ndimage.distance_transform_edt(~surf_a, sampling=spacing)
    dt_b = ndimage.distance_transform_edt(~surf_b, sampling=spacing)
    d = np.concatenate([dt_b[surf_a], dt_a[surf_b]])
    return float(np.percentile(d, 95))


def score_subject(subject: str, fs_seg: np.ndarray, ref_seg: np.ndarray,
                  labels: Dict[int, str] = SUBCORTICAL, with_hd95: bool = True) -> List[StructureScore]:
    out = []
    for lab, name in labels.items():
        a, b = fs_seg == lab, ref_seg == lab
        va, vb = float(np.count_nonzero(a)), float(np.count_nonzero(b))
        out.append(StructureScore(
            subject=subject, label=lab, name=name,
            dice=dice(a, b), vol_fs_mm3=va, vol_ref_mm3=vb,
            vol_diff_pct=float("nan") if vb == 0 else 100.0 * abs(va - vb) / vb,
            hd95_mm=hd95(a, b) if with_hd95 else float("nan"),
        ))
    return out


def compare_subjects(subjects: Iterable[str], fastsurfer_dir: str, freesurfer_dir: str,
                     with_hd95: bool = True, on_missing: str = "skip") -> pd.DataFrame:
    rows: List[StructureScore] = []
    for s in subjects:
        fs_path = os.path.join(fastsurfer_dir, s, FASTSURFER_SEG)
        ref_path = os.path.join(freesurfer_dir, s, FREESURFER_SEG)
        if not (os.path.isfile(fs_path) and os.path.isfile(ref_path)):
            if on_missing == "skip":
                continue
            raise FileNotFoundError(f"{s}: missing {fs_path} or {ref_path}")
        rows.extend(score_subject(s, load_seg(fs_path), load_seg(ref_path), with_hd95=with_hd95))
    return pd.DataFrame([r.__dict__ for r in rows])


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """One row per subject: mean Dice, worst structure, worst HD95. This is what select() reads."""
    g = df.groupby("subject")
    worst = df.loc[g["dice"].idxmin(), ["subject", "name", "dice"]].set_index("subject")
    return pd.DataFrame({
        "mean_dice": g["dice"].mean(),
        "min_dice": g["dice"].min(),
        "worst_structure": worst["name"],
        "max_hd95_mm": g["hd95_mm"].max(),
        "max_vol_diff_pct": g["vol_diff_pct"].max(),
    }).reset_index()


def write_report(df: pd.DataFrame, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, "per_structure.csv"), index=False)
    summarize(df).to_csv(os.path.join(out_dir, "per_subject.csv"), index=False)
