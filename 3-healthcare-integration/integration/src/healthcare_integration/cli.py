"""hci — command line for the bridge.

    hci watch                      run the change-log loop (what the container does)
    hci once                       process pending stable studies once and exit
    hci deid-file in.dcm out.dcm   de-identify a single DICOM file (no servers needed)
    hci reident PSN-XXXXXXXXXXXX   authorized reverse lookup against the vault
    hci aql "<query>"              run AQL against EHRbase and print rows
    hci demo                       push pydicom's sample CT into the source Orthanc to exercise the pipeline
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

import pydicom

from .config import settings
from .deid import Pseudonymizer, deidentify_dataset
from .pipeline import Bridge


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="hci")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watch")
    sub.add_parser("once")
    d = sub.add_parser("deid-file"); d.add_argument("src"); d.add_argument("dst")
    r = sub.add_parser("reident"); r.add_argument("pseudonym")
    q = sub.add_parser("aql"); q.add_argument("query")
    sub.add_parser("demo")
    a = p.parse_args(argv)
    cfg = settings()

    if a.cmd == "watch":
        Bridge(cfg).watch()
    elif a.cmd == "once":
        b = Bridge(cfg); b.ensure_template(); print(f"processed {b.run_once()} studies")
    elif a.cmd == "deid-file":
        ds = pydicom.dcmread(a.src)
        psn = Pseudonymizer(cfg.deid_secret, cfg.deid_namespace, cfg.deid_vault_path)
        ds, warnings = deidentify_dataset(ds, psn, str(ds.PatientID))
        ds.save_as(a.dst, write_like_original=False)
        print(json.dumps({"out": a.dst, "patient": str(ds.PatientID), "warnings": warnings}, ensure_ascii=False))
    elif a.cmd == "reident":
        psn = Pseudonymizer(cfg.deid_secret, cfg.deid_namespace, cfg.deid_vault_path)
        ident = psn.reidentify(a.pseudonym)
        print(ident if ident else "not found (no vault entry)"); sys.exit(0 if ident else 1)
    elif a.cmd == "aql":
        for row in Bridge(cfg).ehr.aql(a.query):
            print(json.dumps(row, ensure_ascii=False))
    elif a.cmd == "demo":
        from pydicom.data import get_testdata_file
        b = Bridge(cfg)
        with open(get_testdata_file("CT_small.dcm"), "rb") as f:
            print(b.src.store(f.read()))
        print("uploaded CT_small.dcm to source Orthanc; the watcher will de-identify it once the study is stable")
