"""Console entry points. Each step reads the previous step's files; nothing is implicit.

    fsf-compare  --subjects subjects.txt --fastsurfer /data/fs --freesurfer /data/recon --out report/
    fsf-select   --report report/ --qc qc.csv --out split.json
    fsf-finetune --split split.json --t1 /data/recon --freesurfer /data/recon --plane coronal --config ft.yaml
    fsf-evaluate --split split.json --t1 /data/recon --freesurfer /data/recon --stock /data/fs \
                 --ckpt-axi runs/finetune/axial_best.pkl --ckpt-cor ... --ckpt-sag ... --out report/eval
"""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd

from . import compare, dataset, evaluate, finetune, select


def _subjects(path: str):
    return [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")]


def compare_main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--subjects", required=True)
    p.add_argument("--fastsurfer", required=True)
    p.add_argument("--freesurfer", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--no-hd95", action="store_true", help="skip surface distance (10x faster)")
    a = p.parse_args()
    df = compare.compare_subjects(_subjects(a.subjects), a.fastsurfer, a.freesurfer, with_hd95=not a.no_hd95)
    compare.write_report(df, a.out)
    print(compare.summarize(df).describe().to_string())


def select_main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--report", required=True)
    p.add_argument("--qc", default=None, help="CSV with columns subject,status (pass/fail)")
    p.add_argument("--site", default=None, help="CSV with columns subject,site for stratified test split")
    p.add_argument("--out", required=True)
    p.add_argument("--dice-min", type=float, default=0.80)
    p.add_argument("--dice-small", type=float, default=0.85)
    a = p.parse_args()
    per_structure = pd.read_csv(os.path.join(a.report, "per_structure.csv"))
    per_subject = pd.read_csv(os.path.join(a.report, "per_subject.csv"))
    qc = pd.read_csv(a.qc) if a.qc else None
    site = dict(pd.read_csv(a.site).itertuples(index=False)) if a.site else None
    cfg = select.SelectionConfig(dice_min=a.dice_min, dice_small=a.dice_small)
    splits = select.split(per_structure, per_subject, cfg, qc=qc, site=site)
    select.write_split(splits, cfg, a.out)
    print({k: len(v) for k, v in splits.items()})


def finetune_main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--split", required=True)
    p.add_argument("--t1", required=True, help="subjects dir holding <sid>/mri/orig.mgz")
    p.add_argument("--freesurfer", required=True, help="subjects dir holding <sid>/mri/aseg.mgz (labels)")
    p.add_argument("--plane", choices=dataset.PLANES, required=True)
    p.add_argument("--config", default=None, help="YAML for FinetuneConfig")
    p.add_argument("--h5-dir", default="runs/h5")
    a = p.parse_args()
    splits = json.load(open(a.split, encoding="utf-8"))["splits"]
    os.makedirs(a.h5_dir, exist_ok=True)
    h5 = {}
    for name in ("train", "val"):
        rows = [(s, os.path.join(a.t1, s), os.path.join(a.freesurfer, s, "mri", "aseg.mgz")) for s in splits[name]]
        h5[name] = os.path.join(a.h5_dir, f"{name}_{a.plane}.h5")
        if not os.path.isfile(h5[name]):
            n = dataset.write_hdf5(rows, a.plane, h5[name])
            print(f"{name}/{a.plane}: {len(rows)} subjects -> {n} slices")
    cfg = finetune.load_config(a.config)
    cfg.plane = a.plane
    hist = finetune.run(cfg, h5["train"], h5["val"])
    print(json.dumps(hist, indent=2))


def evaluate_main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--split", required=True)
    p.add_argument("--t1", required=True)
    p.add_argument("--freesurfer", required=True)
    p.add_argument("--stock", required=True, help="FastSurfer outputs from the released checkpoints")
    p.add_argument("--ckpt-axi", required=True)
    p.add_argument("--ckpt-cor", required=True)
    p.add_argument("--ckpt-sag", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    test = json.load(open(a.split, encoding="utf-8"))["splits"]["test"]
    tuned_dir = os.path.join(a.out, "fastsurfer_tuned")
    evaluate.run_fastsurfer(test, a.t1, tuned_dir,
                            {"axial": a.ckpt_axi, "coronal": a.ckpt_cor, "sagittal": a.ckpt_sag})
    table = evaluate.before_after(test, a.stock, tuned_dir, a.freesurfer)
    os.makedirs(a.out, exist_ok=True)
    table.to_csv(os.path.join(a.out, "before_after.csv"))
    print(table.round(3).to_string())
    print(f"subjects fixed: {table.attrs['subjects_fixed']}  regressed: {table.attrs['subjects_regressed']}")
