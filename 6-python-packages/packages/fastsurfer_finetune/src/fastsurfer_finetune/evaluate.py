"""Step 4: run the fine-tuned checkpoints through FastSurfer's own inference and re-score against FreeSurfer.

We do not evaluate on slices. The product is a 3D segmentation produced by FastSurfer's run_prediction.py,
which aggregates the three plane models by soft voting -- so that is what gets scored, with exactly the same
compare.py metrics as step 1. The report is a before/after table on the held-out test split: per structure
mean Dice and HD95 for the stock checkpoints vs. the fine-tuned ones, plus the count of subjects that
crossed the "hard" thresholds in each direction. A fine-tune that improves hippocampus but regresses
ventricles on the easy subjects fails review; both columns have to move the right way.
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, List

import pandas as pd

from .compare import compare_subjects, summarize
from .labels import fastsurfer_home


def run_fastsurfer(subjects: List[str], t1_dir: str, out_dir: str, ckpts: Dict[str, str],
                   device: str = "cuda") -> None:
    """Segmentation-only FastSurfer run with our checkpoints. One call per subject; sequential is fine here."""
    home = fastsurfer_home()
    for s in subjects:
        cmd = [
            "python", os.path.join(home, "FastSurferCNN", "run_prediction.py"),
            "--t1", os.path.join(t1_dir, s, "mri", "orig.mgz"),
            "--sid", s, "--sd", out_dir,
            "--seg_log", os.path.join(out_dir, s, "seg.log"),
            "--device", device,
        ]
        for plane, path in ckpts.items():          # axial / coronal / sagittal
            cmd += [f"--ckpt_{plane[:3]}", path]
        subprocess.run(cmd, check=True)


def before_after(subjects: List[str], stock_dir: str, tuned_dir: str, freesurfer_dir: str) -> pd.DataFrame:
    before = compare_subjects(subjects, stock_dir, freesurfer_dir)
    after = compare_subjects(subjects, tuned_dir, freesurfer_dir)
    b = before.groupby("name")[["dice", "hd95_mm"]].mean().add_suffix("_stock")
    a = after.groupby("name")[["dice", "hd95_mm"]].mean().add_suffix("_tuned")
    table = b.join(a)
    table["dice_delta"] = table["dice_tuned"] - table["dice_stock"]
    table["hd95_delta_mm"] = table["hd95_mm_tuned"] - table["hd95_mm_stock"]

    sb, sa = summarize(before).set_index("subject"), summarize(after).set_index("subject")
    table.attrs["subjects_fixed"] = int(((sb["min_dice"] < 0.8) & (sa["min_dice"] >= 0.8)).sum())
    table.attrs["subjects_regressed"] = int(((sb["min_dice"] >= 0.8) & (sa["min_dice"] < 0.8)).sum())
    return table.sort_values("dice_delta")
