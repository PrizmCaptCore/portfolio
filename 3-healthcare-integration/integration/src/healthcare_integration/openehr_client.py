"""EHRbase openEHR REST client (openEHR REST API 1.0.x as served under /ehrbase/rest/openehr/v1).

The bridge only ever creates EHRs whose subject is a *pseudonym* in our own namespace:
EHR_STATUS.subject.external_ref = {namespace: DEID_NAMESPACE, id: PSN-...}. EHRbase enforces uniqueness on
(namespace, id), which is what makes "one pseudonymous patient -> one EHR" hold without a lookup table on
this side. Compositions are posted in FLAT (simplified) JSON so the mapping from DICOM tags to template
paths is a plain dict; the template itself (OPT 1.4 XML) is uploaded once at startup.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

FLAT_JSON = "application/openehr.wt.flat.schema+json"


class EHRbaseClient:
    def __init__(self, base_url: str, user: str, password: str, timeout: float = 60.0):
        self._c = httpx.Client(base_url=base_url.rstrip("/"), auth=(user, password), timeout=timeout,
                               headers={"Accept": "application/json"})

    # ---- templates ----
    def template_exists(self, template_id: str) -> bool:
        r = self._c.get(f"/definition/template/adl1.4/{template_id}", headers={"Accept": "application/xml"})
        return r.status_code == 200

    def upload_template(self, opt_xml: bytes) -> None:
        r = self._c.post("/definition/template/adl1.4", content=opt_xml,
                         headers={"Content-Type": "application/xml"})
        if r.status_code not in (201, 204, 409):   # 409 = already there
            r.raise_for_status()

    # ---- EHR per pseudonymous subject ----
    def ehr_for_subject(self, subject_id: str, namespace: str) -> Optional[str]:
        r = self._c.get("/ehr", params={"subject_id": subject_id, "subject_namespace": namespace})
        if r.status_code == 404:
            return None
        return r.raise_for_status().json()["ehr_id"]["value"]

    def create_ehr(self, subject_id: str, namespace: str) -> str:
        status = {
            "_type": "EHR_STATUS",
            "archetype_node_id": "openEHR-EHR-EHR_STATUS.generic.v1",
            "name": {"value": "EHR Status"},
            "subject": {"external_ref": {"id": {"_type": "GENERIC_ID", "value": subject_id, "scheme": namespace},
                                         "namespace": namespace, "type": "PERSON"}},
            "is_modifiable": True, "is_queryable": True,
        }
        r = self._c.post("/ehr", json=status, headers={"Prefer": "return=representation"})
        r.raise_for_status()
        return r.json()["ehr_id"]["value"]

    def ensure_ehr(self, subject_id: str, namespace: str) -> str:
        return self.ehr_for_subject(subject_id, namespace) or self.create_ehr(subject_id, namespace)

    # ---- compositions ----
    def post_composition_flat(self, ehr_id: str, template_id: str, flat: Dict[str, Any]) -> str:
        r = self._c.post(f"/ehr/{ehr_id}/composition", params={"format": "FLAT", "templateId": template_id},
                         content=json.dumps(flat), headers={"Content-Type": FLAT_JSON, "Prefer": "return=minimal"})
        r.raise_for_status()
        # Location: .../composition/<uid>::<system>::<version>
        return r.headers["Location"].rsplit("/", 1)[-1]

    def get_composition_flat(self, ehr_id: str, composition_uid: str) -> Dict[str, Any]:
        r = self._c.get(f"/ehr/{ehr_id}/composition/{composition_uid}", params={"format": "FLAT"},
                        headers={"Accept": FLAT_JSON})
        return r.raise_for_status().json()

    # ---- AQL ----
    def aql(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {"q": query}
        if params:
            body["query_parameters"] = params
        r = self._c.post("/query/aql", json=body).raise_for_status()
        data = r.json()
        cols = [c["name"] for c in data.get("columns", [])]
        return [dict(zip(cols, row)) for row in data.get("rows", [])]

    def studies_for_subject(self, subject_id: str, namespace: str) -> List[Dict[str, Any]]:
        return self.aql(
            "SELECT c/uid/value AS uid, c/context/start_time/value AS start_time, "
            "c/content[openEHR-EHR-OBSERVATION.imaging_exam_result.v0]/data[at0001]/events[at0002]"
            "/data[at0003]/items[at0005]/value/value AS modality "
            "FROM EHR e CONTAINS COMPOSITION c[openEHR-EHR-COMPOSITION.report.v1] "
            "WHERE e/ehr_status/subject/external_ref/id/value = $sid "
            "AND e/ehr_status/subject/external_ref/namespace = $ns ORDER BY start_time DESC",
            {"sid": subject_id, "ns": namespace})

    def close(self) -> None:
        self._c.close()
