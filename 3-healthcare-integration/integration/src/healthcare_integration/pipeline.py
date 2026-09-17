"""The bridge: for every study that becomes stable in the source Orthanc,

    1. read the first instance to get PatientID (the pseudonymization key) and study-level tags
    2. de-identify every instance with the shared Pseudonymizer and push it to the de-id Orthanc
       (quarantine the study instead if any instance carries burned-in-annotation risk)
    3. ensure an EHR exists in EHRbase for the pseudonym, then post an "imaging study summary" composition
       whose dates are shifted and whose only link back to images is the WADO-RS URL on the de-id Orthanc

Idempotent: the de-id Orthanc is checked for the remapped StudyInstanceUID before doing any work, and
EHRbase is queried for an existing composition with the same remapped UID, so re-running after a crash
does not duplicate anything. The change-log cursor is persisted so a restart resumes where it stopped.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import pydicom

from .config import Settings
from .deid import Pseudonymizer, deidentify_dataset
from .openehr_client import EHRbaseClient
from .orthanc_client import OrthancClient

log = logging.getLogger("hci")


def imaging_summary_flat(template_id: str, ds: pydicom.Dataset, n_instances: int, n_series: int,
                         wado_url: str, start_time_iso: str) -> Dict[str, Any]:
    """FLAT composition for the imaging_study_summary template (see templates/README.md for the paths).

    Only de-identified values go in here: ds is the already de-identified first instance.
    """
    t = template_id
    return {
        f"{t}/language|code": "en", f"{t}/language|terminology": "ISO_639-1",
        f"{t}/territory|code": "KR", f"{t}/territory|terminology": "ISO_3166-1",
        f"{t}/category|code": "433", f"{t}/category|value": "event", f"{t}/category|terminology": "openehr",
        f"{t}/context/start_time": start_time_iso,
        f"{t}/context/setting|code": "238", f"{t}/context/setting|value": "other care",
        f"{t}/context/setting|terminology": "openehr",
        f"{t}/composer|name": "orthanc-ehrbase-bridge",
        f"{t}/imaging_examination_result/any_event:0/time": start_time_iso,
        f"{t}/imaging_examination_result/any_event:0/modality": str(getattr(ds, "Modality", "")),
        f"{t}/imaging_examination_result/any_event:0/anatomical_location": str(getattr(ds, "BodyPartExamined", "")),
        f"{t}/imaging_examination_result/any_event:0/overall_result_status|code": "at0009",  # registered
        f"{t}/imaging_examination_result/any_event:0/examination_result_name": str(getattr(ds, "StudyDescription", "")) or "Imaging study",
        f"{t}/imaging_examination_result/any_event:0/imaging_study_uid": str(ds.StudyInstanceUID),
        f"{t}/imaging_examination_result/any_event:0/series_count": n_series,
        f"{t}/imaging_examination_result/any_event:0/instance_count": n_instances,
        f"{t}/imaging_examination_result/any_event:0/multimedia_source/url": wado_url,
        f"{t}/imaging_examination_result/any_event:0/multimedia_source/media_type": "application/dicom",
        f"{t}/imaging_examination_result/any_event:0/deidentification_method": str(ds.DeidentificationMethod),
    }


class Bridge:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.src = OrthancClient(cfg.orthanc_url, cfg.orthanc_user, cfg.orthanc_password)
        self.dst = OrthancClient(cfg.orthanc_deid_url, cfg.orthanc_user, cfg.orthanc_password)
        self.ehr = EHRbaseClient(cfg.ehrbase_url, cfg.ehrbase_user, cfg.ehrbase_password)
        self.psn = Pseudonymizer(cfg.deid_secret, cfg.deid_namespace, cfg.deid_vault_path, cfg.deid_max_shift_days)
        self.cursor_path = os.path.join(os.path.dirname(cfg.deid_vault_path) or ".", "orthanc_changes.cursor")

    # ---- setup ----
    def ensure_template(self) -> None:
        if self.ehr.template_exists(self.cfg.openehr_template_id):
            return
        path = os.path.join(self.cfg.templates_dir, f"{self.cfg.openehr_template_id}.opt")
        with open(path, "rb") as f:
            self.ehr.upload_template(f.read())
        log.info("uploaded template %s", self.cfg.openehr_template_id)

    # ---- one study ----
    def process_study(self, orthanc_study_id: str) -> Optional[str]:
        instances = self.src.study_instances(orthanc_study_id)
        if not instances:
            return None
        first = pydicom.dcmread(io.BytesIO(self.src.instance_file(instances[0]["ID"])), stop_before_pixels=True)
        patient_key = str(first.PatientID)
        new_study_uid = self.psn.uid(str(first.StudyInstanceUID))

        if self.dst.find_study_by_uid(new_study_uid):
            log.info("study %s already de-identified, skipping", new_study_uid)
            return new_study_uid

        # de-identify + push every instance; abort the whole study on burned-in risk
        series: set = set()
        deid_first: Optional[pydicom.Dataset] = None
        pending: List[bytes] = []
        for inst in instances:
            ds = pydicom.dcmread(io.BytesIO(self.src.instance_file(inst["ID"])))
            ds, warnings = deidentify_dataset(ds, self.psn, patient_key)
            if warnings:
                log.warning("quarantine study %s: %s", orthanc_study_id, warnings)
                return None
            series.add(str(ds.SeriesInstanceUID))
            buf = io.BytesIO()
            ds.save_as(buf, write_like_original=False)
            pending.append(buf.getvalue())
            deid_first = deid_first or ds
        for blob in pending:                       # only after every instance passed
            self.dst.store(blob)

        # openEHR side
        assert deid_first is not None
        pseudonym = self.psn.pseudonym(patient_key)
        ehr_id = self.ehr.ensure_ehr(pseudonym, self.cfg.deid_namespace)
        study_date = str(getattr(deid_first, "StudyDate", "")) or "19000101"
        study_time = str(getattr(deid_first, "StudyTime", "000000"))[:6].ljust(6, "0")
        start = f"{study_date[:4]}-{study_date[4:6]}-{study_date[6:8]}T{study_time[:2]}:{study_time[2:4]}:{study_time[4:6]}"
        flat = imaging_summary_flat(self.cfg.openehr_template_id, deid_first, len(instances), len(series),
                                    self.dst.wado_rs_study_url(new_study_uid), start)
        uid = self.ehr.post_composition_flat(ehr_id, self.cfg.openehr_template_id, flat)
        log.info("study %s -> %s / composition %s (pseudonym %s)", orthanc_study_id, new_study_uid, uid, pseudonym)
        return new_study_uid

    # ---- loop ----
    def _load_cursor(self) -> int:
        try:
            return int(open(self.cursor_path).read().strip())
        except (OSError, ValueError):
            return 0

    def _save_cursor(self, seq: int) -> None:
        with open(self.cursor_path, "w") as f:
            f.write(str(seq))

    def run_once(self) -> int:
        n = 0
        since = self._load_cursor()
        for seq, study_id in self.src.stable_studies(since):
            try:
                self.process_study(study_id)
                n += 1
            except Exception:                       # one bad study must not stop the feed
                log.exception("study %s failed", study_id)
            self._save_cursor(seq)
        return n

    def watch(self) -> None:
        self.ensure_template()
        log.info("watching %s every %ss", self.cfg.orthanc_url, self.cfg.poll_interval_sec)
        while True:
            self.run_once()
            time.sleep(self.cfg.poll_interval_sec)
