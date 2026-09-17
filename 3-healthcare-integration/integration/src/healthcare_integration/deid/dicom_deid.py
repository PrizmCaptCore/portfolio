"""DICOM de-identification per PS3.15 Annex E, Basic Application Level Confidentiality Profile, with the
"Retain Longitudinal Temporal Information with Modified Dates" and "Retain Patient Characteristics" options.

What that means in practice:
  * direct identifiers (names, IDs, addresses, phone, institution, operators, physicians, accession) -> removed
    or replaced by the pseudonym
  * every DA/DT/TM element -> shifted by the patient's offset (not zeroed), so longitudinal studies keep order
  * patient characteristics needed for research (sex, age at study, size, weight) -> kept; birth date -> shifted
    then truncated to year (age is what matters, exact DOB is an identifier)
  * all UIDs -> re-mapped consistently (same input UID -> same output UID across the whole study)
  * private tags -> dropped wholesale (vendors put names in them)
  * pixel data -> untouched, but BurnedInAnnotation=YES (or modalities that habitually burn text in: US, XA,
    SC) is flagged so the pipeline can quarantine instead of shipping a face or a name in the pixels
  * the dataset records what happened: PatientIdentityRemoved=YES, DeidentificationMethod, and the
    DeidentificationMethodCodeSequence with the PS3.15 option codes, so a downstream reader can tell which
    profile was applied

This is written against pydicom's Dataset so it works on files from Orthanc, from disk, or from a C-STORE.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Set, Tuple

import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from .pseudonymizer import Pseudonymizer

# Elements replaced with the pseudonym (keyword names, resolved via pydicom's dictionary)
REPLACE_WITH_PSEUDONYM = ("PatientName", "PatientID")

# Elements removed outright (Basic profile "X" / "Z" actions; Z becomes empty string, X is deleted)
REMOVE: Tuple[str, ...] = (
    "OtherPatientIDs", "OtherPatientIDsSequence", "OtherPatientNames", "PatientBirthName", "PatientMotherBirthName",
    "PatientAddress", "PatientTelephoneNumbers", "PatientTelecomInformation", "EthnicGroup", "PatientComments",
    "PatientInsurancePlanCodeSequence", "MilitaryRank", "BranchOfService", "MedicalRecordLocator",
    "PatientReligiousPreference", "ResponsiblePerson", "ResponsibleOrganization", "PatientState",
    "AccessionNumber", "ReferringPhysicianName", "ReferringPhysicianAddress", "ReferringPhysicianTelephoneNumbers",
    "ReferringPhysicianIdentificationSequence", "PhysiciansOfRecord", "PerformingPhysicianName",
    "NameOfPhysiciansReadingStudy", "OperatorsName", "RequestingPhysician", "RequestingService",
    "ConsultingPhysicianName", "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName",
    "InstitutionCodeSequence", "StationName", "DeviceSerialNumber", "PlateID", "CassetteID", "GantryID",
    "StudyID", "RequestAttributesSequence", "ScheduledProcedureStepID", "PerformedProcedureStepID",
    "PerformedProcedureStepDescription", "ImageComments", "AdditionalPatientHistory", "AdmittingDiagnosesDescription",
    "OccupationalHistory", "DerivationDescription", "ContentSequence", "TextValue", "VerifyingObserverName",
    "VerifyingObserverSequence", "PersonName", "CurrentPatientLocation", "RegionOfResidence", "CountryOfResidence",
    "IssuerOfPatientID", "StudyComments", "SeriesComments", "ProtocolName", "IssuerOfAccessionNumberSequence",
)

# Kept on purpose under "Retain Patient Characteristics"
KEEP_CHARACTERISTICS = ("PatientSex", "PatientAge", "PatientSize", "PatientWeight", "PregnancyStatus", "SmokingStatus")

BURNED_IN_RISK_MODALITIES: Set[str] = {"US", "XA", "RF", "SC", "OT", "ES", "XC"}

DEID_METHOD = "PS3.15 E.1 Basic Profile; E.3.6 Retain Longitudinal Temporal Information Modified Dates; " \
              "E.3.7 Retain Patient Characteristics; UIDs remapped; private tags removed"
DEID_CODES = [("113100", "Basic Application Confidentiality Profile"),
              ("113107", "Retain Longitudinal Temporal Information Modified Dates Option"),
              ("113108", "Retain Patient Characteristics Option")]


_DT_FORMATS = {8: "%Y%m%d", 10: "%Y%m%d%H", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}


def _shift_da(value: str, days: int) -> str:
    try:
        return (datetime.strptime(value[:8], "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")
    except ValueError:
        return ""


def _shift_dt(value: str, days: int) -> str:
    """DT = YYYYMMDDHHMMSS.FFFFFF&ZZXX; shift the date part, keep fraction and offset verbatim."""
    tz_pos = max(value.rfind("+"), value.rfind("-"))
    core, tz = (value[:tz_pos], value[tz_pos:]) if tz_pos > 0 else (value, "")
    base, _, frac = core.partition(".")
    fmt = _DT_FORMATS.get(len(base))
    if fmt is None:
        return ""
    try:
        shifted = (datetime.strptime(base, fmt) + timedelta(days=days)).strftime(fmt)
    except ValueError:
        return ""
    return shifted + (f".{frac}" if frac else "") + tz


def _walk(ds: Dataset) -> Iterable[Tuple[Dataset, pydicom.DataElement]]:
    for el in list(ds):
        yield ds, el
        if el.VR == "SQ":
            for item in el.value:
                yield from _walk(item)


def burned_in_risk(ds: Dataset) -> bool:
    if str(getattr(ds, "BurnedInAnnotation", "")).upper() == "YES":
        return True
    return str(getattr(ds, "Modality", "")).upper() in BURNED_IN_RISK_MODALITIES


def deidentify_dataset(ds: Dataset, psn: Pseudonymizer, patient_key: str) -> Tuple[Dataset, List[str]]:
    """De-identify in place. Returns (dataset, warnings). patient_key is the source PatientID."""
    warnings: List[str] = []
    pseudonym = psn.pseudonym(patient_key)
    days = psn.shift_days(patient_key)

    if burned_in_risk(ds):
        warnings.append("burned-in annotation risk: pixel data not de-identified")

    # 1. private tags first (they can hide names in any VR)
    ds.remove_private_tags()

    # 2. walk every element, including inside sequences
    for parent, el in _walk(ds):
        kw = el.keyword
        if kw in REPLACE_WITH_PSEUDONYM:
            el.value = pseudonym
        elif kw in REMOVE:
            del parent[el.tag]
        elif el.VR == "UI" and kw not in ("SOPClassUID", "TransferSyntaxUID", "MediaStorageSOPClassUID"):
            el.value = psn.uid(str(el.value))
        elif el.VR == "DA" and el.value:
            el.value = _shift_da(str(el.value), days)
        elif el.VR == "DT" and el.value:
            el.value = _shift_dt(str(el.value), days)
        # TM (time of day) is kept: shifting by whole days leaves it unchanged, and it carries no identity.
        elif el.VR == "PN" and kw not in REPLACE_WITH_PSEUDONYM:
            del parent[el.tag]           # any person name we did not explicitly handle

    # 3. birth date: shifted like everything else, then truncated to the year
    if "PatientBirthDate" in ds and ds.PatientBirthDate:
        ds.PatientBirthDate = ds.PatientBirthDate[:4] + "0101"

    # 4. file meta must follow the remapped SOP Instance UID
    if hasattr(ds, "file_meta") and "MediaStorageSOPInstanceUID" in ds.file_meta:
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

    # 5. say what we did
    ds.PatientIdentityRemoved = "YES"
    ds.DeidentificationMethod = DEID_METHOD
    seq = Sequence()
    for code, meaning in DEID_CODES:
        item = Dataset()
        item.CodeValue, item.CodingSchemeDesignator, item.CodeMeaning = code, "DCM", meaning
        seq.append(item)
    ds.DeidentificationMethodCodeSequence = seq
    ds.LongitudinalTemporalInformationModified = "MODIFIED"
    return ds, warnings
