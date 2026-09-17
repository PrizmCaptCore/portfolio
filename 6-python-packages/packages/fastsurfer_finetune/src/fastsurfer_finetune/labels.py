"""Label vocabularies shared by comparison and training (FastSurfer v1 conventions).

FreeSurfer's aseg/aparc use FreeSurferColorLUT ids on disk. FastSurferCNN v1 predicts a compact index:
79 classes for axial/coronal (background + CLASS_NAMES) and 51 for sagittal (hemispheres merged,
background + CLASS_NAMES_SAG). The mapping functions live in FastSurfer's data_loader and are imported at
runtime from FASTSURFER_HOME so this package never hardcodes them and drifts from the checkpoint.

  * SUBCORTICAL: LUT ids scored in the comparison step. Cortical parcels are excluded on purpose --
    FreeSurfer's cortex comes from a surface pipeline a volumetric CNN cannot reproduce, so cortical
    disagreement is expected and is not a signal that the CNN is wrong.
  * subcortical_class_indices(plane): the same idea in the CNN's class space, used for early stopping.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List

# FreeSurferColorLUT ids for the subcortical structures used to judge agreement.
SUBCORTICAL: Dict[int, str] = {
    2: "Left-Cerebral-White-Matter", 41: "Right-Cerebral-White-Matter",
    4: "Left-Lateral-Ventricle", 43: "Right-Lateral-Ventricle",
    5: "Left-Inf-Lat-Vent", 44: "Right-Inf-Lat-Vent",
    7: "Left-Cerebellum-White-Matter", 46: "Right-Cerebellum-White-Matter",
    8: "Left-Cerebellum-Cortex", 47: "Right-Cerebellum-Cortex",
    10: "Left-Thalamus-Proper", 49: "Right-Thalamus-Proper",
    11: "Left-Caudate", 50: "Right-Caudate",
    12: "Left-Putamen", 51: "Right-Putamen",
    13: "Left-Pallidum", 52: "Right-Pallidum",
    17: "Left-Hippocampus", 53: "Right-Hippocampus",
    18: "Left-Amygdala", 54: "Right-Amygdala",
    26: "Left-Accumbens-area", 58: "Right-Accumbens-area",
    28: "Left-VentralDC", 60: "Right-VentralDC",
    31: "Left-choroid-plexus", 63: "Right-choroid-plexus",
    14: "3rd-Ventricle", 15: "4th-Ventricle", 16: "Brain-Stem",
    24: "CSF", 77: "WM-hypointensities",
}

# Small structures where FastSurfer is weakest; they get a stricter threshold in select().
SMALL_STRUCTURES = {17, 53, 18, 54, 26, 58, 13, 52}


def fastsurfer_home() -> str:
    """Return the FastSurfer checkout and make its v1 modules importable.

    v1 scripts import each other as top-level modules (``from models.networks import ...``), so the
    FastSurferCNN/ directory itself has to be on sys.path, not just the repo root.
    """
    home = os.environ.get("FASTSURFER_HOME")
    if not home or not os.path.isdir(os.path.join(home, "FastSurferCNN")):
        raise RuntimeError("set FASTSURFER_HOME to a FastSurfer v1 checkout "
                           "(branch feature/one-shot-bias-field; needs FastSurferCNN/ and recon_surf/)")
    for p in (home, os.path.join(home, "FastSurferCNN")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return home


def class_names(plane: str) -> List[str]:
    """Class names in checkpoint order, index 0 = background (as FastSurferCNN/train.py defines them)."""
    fastsurfer_home()
    import train as fs_train  # type: ignore  # FastSurferCNN/train.py; importing does not run train()

    names = fs_train.CLASS_NAMES_SAG if plane == "sagittal" else fs_train.CLASS_NAMES
    return ["Background"] + list(names)


def subcortical_class_indices(plane: str) -> List[int]:
    """Compact class indices of the non-cortical structures (everything that is not a ctx-* parcel)."""
    return [i for i, n in enumerate(class_names(plane)) if i > 0 and not n.startswith("ctx-")]


def num_classes(plane: str) -> int:
    return 51 if plane == "sagittal" else 79
