"""De-identify an openEHR composition in FLAT form with the same pseudonymizer the DICOM side uses.

openEHR keeps the subject on the EHR (EHR_STATUS.subject), not in the composition, so the main identity
risk inside a composition is (a) composer / participation names, (b) absolute dates in context and events,
(c) free text. Rules, applied over the FLAT key/value map:

  * keys ending in composer|name, participation.*name, health_care_facility|name -> dropped
  * any value that parses as ISO-8601 date/datetime -> shifted by the patient's offset
  * keys whose path contains identifiers you would not expect in the template but that appear in practice
    (mrn, external_ref|id, accession) -> replaced by the pseudonym
  * free-text values (keys not ending in |code, |value with a code sibling, |magnitude, |unit) -> regex redaction
    of phone numbers, emails, national ids and "Dr. <Name>" patterns. This is a backstop, not a guarantee:
    unstructured narrative can only be made safe by a human or a clinical NER model.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .pseudonymizer import Pseudonymizer

DROP_KEY_SUFFIXES = ("composer|name", "composer|id", "|name", "health_care_facility|id")
DROP_KEY_PARTS = ("participation", "composer")
ID_KEY_PARTS = ("external_ref|id", "mrn", "patient_id", "accession", "subject|id")

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:?\d{2}|Z)?)?$")
REDACT = [
    (re.compile(r"\b\d{6}-\d{7}\b"), "[ID]"),                          # KR resident registration number
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ID]"),                    # US SSN pattern
    (re.compile(r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"\b(Dr|Prof|Mr|Mrs|Ms)\.?\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?"), r"\1. [NAME]"),
    (re.compile(r"(환자|보호자)\s*[가-힣]{2,4}(님|씨)"), r"\1 [NAME]"),
]


def _is_free_text(key: str, flat: Dict[str, Any]) -> bool:
    if key.endswith(("|code", "|terminology", "|magnitude", "|unit", "|id", "|scheme", "|namespace")):
        return False
    if key.endswith("|value") and key[:-6] + "|code" in flat:   # coded text: the label is not free text
        return False
    return True


def _shift_iso(value: str, days: int) -> str:
    v = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return value
    from datetime import timedelta
    out = dt + timedelta(days=days)
    return out.date().isoformat() if len(value) == 10 else out.isoformat()


def deidentify_flat(flat: Dict[str, Any], psn: Pseudonymizer, patient_key: str) -> Tuple[Dict[str, Any], List[str]]:
    """Return (deidentified FLAT map, warnings). patient_key is the source identifier (same one used for DICOM)."""
    pseudonym = psn.pseudonym(patient_key)
    days = psn.shift_days(patient_key)
    out: Dict[str, Any] = {}
    warnings: List[str] = []
    for key, value in flat.items():
        lk = key.lower()
        if any(lk.endswith(s) for s in DROP_KEY_SUFFIXES) and any(p in lk for p in DROP_KEY_PARTS):
            continue
        if any(p in lk for p in ID_KEY_PARTS):
            out[key] = pseudonym
            continue
        if isinstance(value, str) and ISO.match(value):
            out[key] = _shift_iso(value, days)
            continue
        if isinstance(value, str) and _is_free_text(key, flat):
            redacted = value
            for pat, repl in REDACT:
                redacted = pat.sub(repl, redacted)
            if redacted != value:
                warnings.append(f"redacted free text in {key}")
            out[key] = redacted
            continue
        out[key] = value
    return out, warnings
