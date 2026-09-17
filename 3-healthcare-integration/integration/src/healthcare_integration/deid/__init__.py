"""De-identification: one policy, applied to both the DICOM side and the openEHR side.

pseudonymizer  -> stable pseudonyms + per-patient date shift + re-identification vault
dicom_deid     -> DICOM PS3.15 basic profile with "retain longitudinal (modified dates)" + "retain patient characteristics"
openehr_deid   -> the same pseudonym/date shift applied to FLAT compositions, plus free-text redaction
"""
from .pseudonymizer import Pseudonymizer
from .dicom_deid import deidentify_dataset
from .openehr_deid import deidentify_flat

__all__ = ["Pseudonymizer", "deidentify_dataset", "deidentify_flat"]
