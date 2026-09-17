"""Label vocabularies shared by comparison and training.

FreeSurfer's aseg/aparc use the FreeSurferColorLUT ids. FastSurfer's aparc.DKTatlas+aseg.deep.mgz uses
the same ids on disk, but the network itself predicts a compact class index (0..N-1). Two mappings live here:

  * SUBCORTICAL: the structures we score in the comparison step. Cortical parcels are excluded on purpose --
    FreeSurfer's cortical labels come from a surface-based pipeline that FastSurfer's volumetric CNN cannot
    reproduce exactly, so cortical disagreement is expected and is not a signal that the CNN is wrong.
  * lut_to_class / class_to_lut: FreeSurfer id <-> FastSurfer class index, taken from the FastSurfer repo at
    runtime (FASTSURFER_HOME) so this package never hardcodes the 78/51-class vocabularies and drifts from
    the checkpoint it fine-tunes.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Tuple

import numpy as np

# FreeSurferColorLUT ids for the subcortical structures used to judge agreement.
SUBCORTICAL: Dict[int, str] = {
    2: "Left-Cerebral-White-Matter", 41: "Right-Cerebral-White-Matter",
    3: "Left-Cerebral-Cortex", 42: "Right-Cerebral-Cortex",
    4: "Left-Lateral-Ventricle", 43: "Right-Lateral-Ventricle",
    7: "Left-Cerebellum-White-Matter", 46: "Right-Cerebellum-White-Matter",
    8: "Left-Cerebellum-Cortex", 47: "Right-Cerebellum-Cortex",
    10: "Left-Thalamus", 49: "Right-Thalamus",
    11: "Left-Caudate", 50: "Right-Caudate",
    12: "Left-Putamen", 51: "Right-Putamen",
    13: "Left-Pallidum", 52: "Right-Pallidum",
    17: "Left-Hippocampus", 53: "Right-Hippocampus",
    18: "Left-Amygdala", 54: "Right-Amygdala",
    26: "Left-Accumbens-area", 58: "Right-Accumbens-area",
    28: "Left-VentralDC", 60: "Right-VentralDC",
    14: "3rd-Ventricle", 15: "4th-Ventricle", 16: "Brain-Stem",
    24: "CSF", 77: "WM-hypointensities",
}

# Small structures where FastSurfer is known to be weakest; they get a stricter threshold in select().
SMALL_STRUCTURES = {17, 53, 18, 54, 26, 58, 13, 52}


def fastsurfer_home() -> str:
    home = os.environ.get("FASTSURFER_HOME")
    if not home or not os.path.isdir(os.path.join(home, "FastSurferCNN")):
        raise RuntimeError("set FASTSURFER_HOME to a FastSurfer checkout (needs FastSurferCNN/)")
    if home not in sys.path:
        sys.path.insert(0, home)
    return home


def lut_mappings(plane: str) -> Tuple[np.ndarray, np.ndarray]:
    """(lut_to_class, class_to_lut) for the given plane, from FastSurfer's own data_utils.

    Sagittal merges left/right into one class set (51 classes); axial/coronal keep laterality (78).
    Returning arrays instead of dicts lets the dataset map a whole volume with one fancy-index op.
    """
    fastsurfer_home()
    from FastSurferCNN.data_loader import data_utils as du  # type: ignore

    labels, labels_sag = du.get_labels_from_lut(du.get_lut())
    lut_ids = labels_sag if plane == "sagittal" else labels
    class_to_lut = np.asarray(lut_ids, dtype=np.int32)
    lut_to_class = np.zeros(int(class_to_lut.max()) + 1, dtype=np.int32)  # unknown ids -> 0 (background)
    lut_to_class[class_to_lut] = np.arange(len(class_to_lut), dtype=np.int32)
    return lut_to_class, class_to_lut


def merge_hemispheres(seg: np.ndarray) -> np.ndarray:
    """Sagittal training target: right-hemisphere ids folded onto left ids (FastSurfer convention)."""
    fastsurfer_home()
    from FastSurferCNN.data_loader import data_utils as du  # type: ignore

    return du.map_label2sagittal(seg) if hasattr(du, "map_label2sagittal") else du.sagittal_coronal_remap_lookup(seg)
