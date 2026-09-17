"""Step 4: run the fine-tuned checkpoints through FastSurfer v1's own eval.py and re-score against FreeSurfer.

We do not evaluate on slices. The product is a 3D segmentation produced by FastSurferCNN/eval.py, which
runs the three plane networks and aggregates them by view aggregation (soft voting, sagittal mapped back to
the lateralised label space) -- so that is what gets scored, with exactly the same compare.py metrics as
step 1. The report is a before/after table on the held-out test split: per structure mean Dice and HD95 for
the stock Epoch_30 checkpoints vs. the fine-tuned ones, plus how many subjects crossed the "hard" thresholds
in each direction. A fine-tune that improves hippocampus but regresses ventricles on the easy subjects fails
review; both columns have to move the right way.
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, List

import pandas as pd

from .compare import compare_subjects, summarize
from .labels import fastsurfer_home


def run_fastsurfer(subjects: List[str], t1_dir: str, out_dir: str, ckpts: Dict[str, str],
                   in_name: str = os.path.join("mri", "orig_nu.mgz"), use_cuda: bool = True) -> None:
    """Segmentation-only run with our checkpoints via v1's eval.py (one subject per call, --t <sid>).

    in_name must match what the networks were fine-tuned on (orig_nu.mgz after preprocess.py, or orig.mgz).
    Output lands at <out_dir>/<sid>/mri/aparc.DKTatlas+aseg.deep.mgz so compare.py finds it unchanged.
    """
    home = fastsurfer_home()
    for s in subjects:
        cmd = [
            "python", os.path.join(home, "FastSurferCNN", "eval.py"),
            "--i_dir", t1_dir, "--o_dir", out_dir, "--t", s,
            "--in_name", in_name,
            "--out_name", os.path.join("mri", "aparc.DKTatlas+aseg.deep.mgz"),
            "--network_axial_path", ckpts["axial"],
            "--network_coronal_path", ckpts["coronal"],
            "--network_sagittal_path", ckpts["sagittal"],
            "--batch_size", "8",
        ]
        if not use_cuda:
            cmd.append("--no_cuda")
        subprocess.run(cmd, check=True, cwd=os.path.join(home, "FastSurferCNN"))


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
