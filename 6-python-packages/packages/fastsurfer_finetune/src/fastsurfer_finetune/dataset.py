"""Step 3a: subjects -> the HDF5 layout FastSurferCNN v1 trains on.

v1's generate_hdf5.PopulationDataset already does everything the network needs: FreeSurfer aparc+aseg ->
compact labels (map_aparc_aseg2label, with the no-CC aseg used to mask corpus callosum), median-frequency x
edge weight masks (create_weight_mask), plane transposition, 7-slice thick stacks (get_thick_slices) and
blank-slice filtering. Re-implementing any of it here would only risk producing tensors the released
checkpoint was not trained on. So this module writes a subject-list CSV for our split and calls
PopulationDataset with the same parameters train.py expects:

    orig_dataset   (N, 256, 256, 7) float32
    aseg_dataset   (N, 256, 256)    uint8    compact class index, 0 = background
    weight_dataset (N, 256, 256)    float32
    subject        (N_subjects,)    str

The only knob we add is image_name: mri/orig.mgz (stock) or mri/orig_nu.mgz (after preprocess.py).
"""
from __future__ import annotations

import os
from typing import Iterable

from .labels import fastsurfer_home

PLANES = ("axial", "coronal", "sagittal")
GT_NAME = os.path.join("mri", "aparc.DKTatlas+aseg.mgz")      # FreeSurfer recon-all label
GT_NOCC = os.path.join("mri", "aseg.auto_noCCseg.mgz")        # FreeSurfer's, used to mask CC out of the GT


def write_hdf5(subject_dirs: Iterable[str], plane: str, out_path: str,
               image_name: str = os.path.join("mri", "orig_nu.mgz"), thickness: int = 3) -> str:
    """Build one plane HDF5 from FreeSurfer subject directories. Returns the path written."""
    fastsurfer_home()
    from generate_hdf5 import PopulationDataset  # type: ignore  # FastSurferCNN/generate_hdf5.py

    subject_dirs = [os.path.abspath(d) for d in subject_dirs]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    csv_path = out_path + ".subjects.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("\n".join(subject_dirs) + "\n")

    params = {
        "dataset_name": out_path, "height": 256, "width": 256,
        "data_path": None, "thickness": thickness, "csv_file": csv_path, "pattern": "*",
        "image_name": image_name, "gt_name": GT_NAME, "gt_nocc": GT_NOCC,
    }
    PopulationDataset(params).create_hdf5_dataset(plane=plane)
    return out_path
