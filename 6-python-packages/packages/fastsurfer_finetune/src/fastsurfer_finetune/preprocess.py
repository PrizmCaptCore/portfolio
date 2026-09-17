"""Step 0: one-shot bias field correction (what the feature/one-shot-bias-field branch adds).

Stock FastSurfer v1 runs N4 (SimpleITK) on orig.mgz inside recon-surf. The branch replaces that with
recon_surf/bias_field_correction.py: it takes the CNN segmentation as a tissue prior, clusters labels into
a handful of Gaussians (GM, WM, CSF, thalamus, ...), fits a smooth DCT bias field to the log-intensities in
ONE pass (no iterative N4 re-estimation), divides it out and rescales white matter to ~110 (--norm).
recon-surf.sh on the branch calls it as

    bias_field_correction.py --image orig.mgz --seg aseg.auto_noCCseg.mgz --out orig_nu.mgz --bf bias_field.mgz --norm

For fine-tuning we run the same script on every subject up front and train on orig_nu.mgz, because the
disagreement we were chasing tracked scanner shading: the CNN mislabelled hippocampus/amygdala exactly where
the field was strongest, and correcting the input moved more Dice than any loss tweak. The seg passed as
prior is FastSurfer's own output reduced to aseg labels, so the step depends on nothing from FreeSurfer.
"""
from __future__ import annotations

import os
import subprocess
from typing import Iterable, List

from .labels import fastsurfer_home

DEEP_SEG = os.path.join("mri", "aparc.DKTatlas+aseg.deep.mgz")
NOCC_SEG = os.path.join("mri", "aseg.auto_noCCseg.mgz")


def reduce_to_aseg(subject_dir: str) -> str:
    """Deep DKT+aseg -> aseg-only labels (drops cortical parcels), as recon-surf.sh does before the CC step."""
    home = fastsurfer_home()
    out = os.path.join(subject_dir, NOCC_SEG)
    if not os.path.isfile(out):
        subprocess.run(["python", os.path.join(home, "recon_surf", "reduce_to_aseg.py"),
                        "-i", os.path.join(subject_dir, DEEP_SEG), "-o", out], check=True)
    return out


def bias_correct(subject_dir: str, image_name: str = "orig.mgz", out_name: str = "orig_nu.mgz",
                 norm: bool = True) -> str:
    """Run the branch's one-shot correction for one subject; returns the corrected image path."""
    home = fastsurfer_home()
    mri = os.path.join(subject_dir, "mri")
    out = os.path.join(mri, out_name)
    if os.path.isfile(out):
        return out
    cmd = ["python", os.path.join(home, "recon_surf", "bias_field_correction.py"),
           "--image", os.path.join(mri, image_name),
           "--seg", reduce_to_aseg(subject_dir),
           "--out", out,
           "--bf", os.path.join(mri, "bias_field.mgz")]
    if norm:
        cmd.append("--norm")
    subprocess.run(cmd, check=True, cwd=mri)  # script writes relative paths next to the image
    return out


def bias_correct_all(subject_dirs: Iterable[str]) -> List[str]:
    return [bias_correct(d) for d in subject_dirs]
