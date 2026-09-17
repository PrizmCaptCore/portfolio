"""Step 3a: subjects -> 2.5D slice tensors in the format FastSurferCNN trains on.

FastSurferCNN is three 2D networks (axial, coronal, sagittal) whose input is a *thick slice*: the target slice
plus 3 neighbours on each side, stacked as 7 channels. Labels are the FreeSurfer aseg mapped to the compact
class index, and every slice carries a weight mask = median-frequency class weight x (1 + edge weight), so the
loss does not drown small structures under white matter. All of that logic exists in FastSurfer's
data_utils; this module only orchestrates it over our split and writes one HDF5 per plane, matching what
FastSurferCNN/generate_hdf5.py produces so the stock training loop can consume it unchanged.
"""
from __future__ import annotations

import os
from typing import Iterable, List, Tuple

import h5py
import nibabel as nib
import numpy as np

from .labels import fastsurfer_home, lut_mappings, merge_hemispheres

PLANES = ("axial", "coronal", "sagittal")
THICKNESS = 3  # neighbours per side -> 7-channel input


def _to_plane(vol: np.ndarray, plane: str) -> np.ndarray:
    """Conformed LIA volume -> (n_slices, H, W) along the requested plane, FastSurfer orientation."""
    if plane == "axial":
        return np.transpose(vol, (1, 0, 2))     # slice along the I/S axis
    if plane == "coronal":
        return np.transpose(vol, (2, 0, 1))     # slice along A/P
    return vol                                   # sagittal: already slice-first (L/R)


def _thick(vol_p: np.ndarray, t: int = THICKNESS) -> np.ndarray:
    """(n, H, W) -> (n, H, W, 2t+1) by stacking neighbouring slices, edge-padded."""
    pad = np.pad(vol_p, ((t, t), (0, 0), (0, 0)), mode="edge")
    return np.stack([pad[i:i + vol_p.shape[0]] for i in range(2 * t + 1)], axis=-1)


def _weight_mask(labels_p: np.ndarray, n_classes: int) -> np.ndarray:
    """Median-frequency balancing x edge emphasis, per FastSurfer's recipe."""
    fastsurfer_home()
    from FastSurferCNN.data_loader import data_utils as du  # type: ignore

    return du.create_weight_mask(labels_p, max_weight=5, max_edge_weight=5, ctx_thresh=n_classes).astype(np.float32)


def subject_arrays(subject_dir: str, ref_seg_path: str, plane: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(images (n,H,W,7) uint8, labels (n,H,W) int16, weights (n,H,W) float32) for one subject and plane."""
    t1 = np.asanyarray(nib.load(os.path.join(subject_dir, "mri", "orig.mgz")).dataobj).astype(np.uint8)
    seg = np.asanyarray(nib.load(ref_seg_path).dataobj).astype(np.int32)
    if plane == "sagittal":
        seg = merge_hemispheres(seg)
    lut_to_class, class_to_lut = lut_mappings(plane)
    seg = np.where(seg < len(lut_to_class), seg, 0)
    cls = lut_to_class[seg].astype(np.int16)

    t1_p, cls_p = _to_plane(t1, plane), _to_plane(cls, plane)
    keep = cls_p.reshape(cls_p.shape[0], -1).any(axis=1)  # drop empty slices (skull-only / outside brain)
    imgs = _thick(t1_p)[keep]
    labs = cls_p[keep]
    return imgs, labs, _weight_mask(labs, len(class_to_lut))


def write_hdf5(subjects: Iterable[Tuple[str, str, str]], plane: str, out_path: str) -> int:
    """subjects: (subject_id, subject_dir_with_orig, freesurfer_aseg_path). Returns slice count."""
    n, sids = 0, []
    with h5py.File(out_path, "w") as f:
        img_ds = lab_ds = w_ds = None
        for sid, sdir, seg_path in subjects:
            sids.append(sid)
            imgs, labs, w = subject_arrays(sdir, seg_path, plane)
            if img_ds is None:
                img_ds = f.create_dataset("orig_dataset", data=imgs, maxshape=(None,) + imgs.shape[1:], chunks=True)
                lab_ds = f.create_dataset("aseg_dataset", data=labs, maxshape=(None,) + labs.shape[1:], chunks=True)
                w_ds = f.create_dataset("weight_dataset", data=w, maxshape=(None,) + w.shape[1:], chunks=True)
            else:
                for ds, arr in ((img_ds, imgs), (lab_ds, labs), (w_ds, w)):
                    ds.resize(ds.shape[0] + arr.shape[0], axis=0)
                    ds[-arr.shape[0]:] = arr
            n += imgs.shape[0]
        f.attrs["plane"] = plane
        f.attrs["n_slices"] = n
        f.attrs["subjects"] = np.array(sids, dtype=h5py.string_dtype())
    return n
