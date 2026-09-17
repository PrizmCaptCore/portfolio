"""Thin Orthanc REST client. Only the calls the bridge needs; no DICOM networking (Orthanc does that).

Orthanc identifiers (the SHA-1-looking ids in URLs) are Orthanc-internal and differ between the source and
de-id instances even for the same study, so the bridge keys everything on DICOM StudyInstanceUID instead.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

import httpx


class OrthancClient:
    def __init__(self, base_url: str, user: str, password: str, timeout: float = 120.0):
        self._c = httpx.Client(base_url=base_url.rstrip("/"), auth=(user, password), timeout=timeout)

    # ---- discovery ----
    def changes(self, since: int, limit: int = 100) -> Dict[str, Any]:
        """Orthanc's change log; we react to StableStudy so we never process a half-received study."""
        return self._c.get("/changes", params={"since": since, "limit": limit}).raise_for_status().json()

    def stable_studies(self, since: int) -> Iterator[tuple[int, str]]:
        """Yield (seq, orthanc_study_id) for every StableStudy change after `since`, following the log."""
        while True:
            page = self.changes(since)
            for ch in page["Changes"]:
                if ch["ChangeType"] == "StableStudy":
                    yield ch["Seq"], ch["ID"]
            if page["Done"]:
                return
            since = page["Last"]

    def study(self, orthanc_id: str) -> Dict[str, Any]:
        return self._c.get(f"/studies/{orthanc_id}").raise_for_status().json()

    def study_instances(self, orthanc_id: str) -> List[Dict[str, Any]]:
        return self._c.get(f"/studies/{orthanc_id}/instances").raise_for_status().json()

    def find_study_by_uid(self, study_instance_uid: str) -> Optional[str]:
        hits = self._c.post("/tools/find", json={"Level": "Study", "Query": {"StudyInstanceUID": study_instance_uid}}) \
            .raise_for_status().json()
        return hits[0] if hits else None

    # ---- instance transfer ----
    def instance_file(self, orthanc_instance_id: str) -> bytes:
        return self._c.get(f"/instances/{orthanc_instance_id}/file").raise_for_status().content

    def store(self, dicom_bytes: bytes) -> Dict[str, Any]:
        return self._c.post("/instances", content=dicom_bytes,
                            headers={"Content-Type": "application/dicom"}).raise_for_status().json()

    # ---- links for the openEHR side ----
    def wado_rs_study_url(self, study_instance_uid: str) -> str:
        return f"{self._c.base_url}/dicom-web/studies/{study_instance_uid}"

    def close(self) -> None:
        self._c.close()
