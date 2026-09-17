"""Step 2: turn comparison scores into a fine-tuning split.

The point of fine-tuning was never "make FastSurfer copy FreeSurfer everywhere" -- on most subjects the two
already agree within Dice 0.9 and there is nothing to learn. The signal is in the tail: subjects (or
scanners, or age groups) where the CNN systematically diverges. So the training set is built as

    hard  = subjects whose min structure Dice < DICE_MIN, or any SMALL_STRUCTURES Dice < DICE_SMALL,
            or max HD95 > HD95_MAX          -> after manual QC, FreeSurfer becomes the label
    easy  = a random sample of agreeing subjects, EASY_RATIO * len(hard)
            -> anchors; without them the model drifts on the cases it already got right

and a held-out test split is drawn *before* any of this, stratified by site, so the evaluation never sees a
subject that influenced selection. QC status comes from a CSV a human fills in; subjects without a "pass" are
excluded from training even if they are hard cases -- a FreeSurfer failure must not become a label.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .labels import SMALL_STRUCTURES


@dataclass
class SelectionConfig:
    dice_min: float = 0.80        # any subcortical structure below this -> hard
    dice_small: float = 0.85      # hippocampus/amygdala/accumbens/pallidum threshold
    hd95_max_mm: float = 3.0
    easy_ratio: float = 0.5       # agreeing subjects kept per hard subject
    test_frac: float = 0.15
    seed: int = 0


def split(per_structure: pd.DataFrame, per_subject: pd.DataFrame, cfg: SelectionConfig,
          qc: Optional[pd.DataFrame] = None, site: Optional[Dict[str, str]] = None) -> Dict[str, List[str]]:
    rng = np.random.default_rng(cfg.seed)
    subjects = per_subject["subject"].tolist()

    # 1. hold out a test set first, stratified by site when known
    site_of = site or {s: "unknown" for s in subjects}
    test: List[str] = []
    for _, group in pd.Series(subjects).groupby(pd.Series(subjects).map(site_of)):
        ids = group.tolist()
        rng.shuffle(ids)
        test.extend(ids[: max(1, int(len(ids) * cfg.test_frac))])
    pool = [s for s in subjects if s not in set(test)]

    # 2. hard vs easy on the remaining pool
    small = per_structure[per_structure["label"].isin(SMALL_STRUCTURES)].groupby("subject")["dice"].min()
    ps = per_subject.set_index("subject")
    hard, easy = [], []
    for s in pool:
        is_hard = (ps.loc[s, "min_dice"] < cfg.dice_min
                   or small.get(s, 1.0) < cfg.dice_small
                   or ps.loc[s, "max_hd95_mm"] > cfg.hd95_max_mm)
        (hard if is_hard else easy).append(s)

    # 3. QC gate: only subjects a human passed can carry FreeSurfer as a label
    if qc is not None:
        passed = set(qc.loc[qc["status"].str.lower() == "pass", "subject"])
        hard = [s for s in hard if s in passed]
        easy = [s for s in easy if s in passed]

    rng.shuffle(easy)
    easy = easy[: int(len(hard) * cfg.easy_ratio)]
    train = hard + easy
    rng.shuffle(train)
    n_val = max(1, int(len(train) * 0.1))
    return {"train": train[n_val:], "val": train[:n_val], "test": test,
            "hard": hard, "easy": easy}


def write_split(splits: Dict[str, List[str]], cfg: SelectionConfig, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"config": asdict(cfg), "splits": splits}, f, indent=2)
