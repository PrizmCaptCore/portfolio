"""Offline tests: no Orthanc or EHRbase needed."""
import pydicom
from pydicom.data import get_testdata_file

from healthcare_integration.deid import Pseudonymizer, deidentify_dataset, deidentify_flat

SECRET = "0" * 64


def test_pseudonym_is_deterministic_and_keyed():
    a = Pseudonymizer(SECRET, "ns")
    b = Pseudonymizer("1" * 64, "ns")
    assert a.pseudonym("MRN-1") == a.pseudonym("MRN-1")
    assert a.pseudonym("MRN-1") != a.pseudonym("MRN-2")
    assert a.pseudonym("MRN-1") != b.pseudonym("MRN-1")
    assert a.pseudonym("MRN-1").startswith("PSN-")


def test_shift_is_bounded_and_per_patient():
    p = Pseudonymizer(SECRET, "ns", max_shift_days=30)
    for i in range(200):
        assert -30 <= p.shift_days(f"P{i}") <= 30
    assert p.shift_days("P1") == p.shift_days("P1")


def test_vault_roundtrip(tmp_path):
    p = Pseudonymizer(SECRET, "ns", vault_path=str(tmp_path / "v.sqlite"))
    psn = p.pseudonym("MRN-42")
    assert p.reidentify(psn) == "MRN-42"
    assert Pseudonymizer(SECRET, "ns").reidentify(psn) is None   # anonymization mode: no vault, no way back


def test_dicom_deid_removes_identity_and_keeps_intervals():
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    ds.PatientName = "Doe^Jane"
    ds.PatientID = "MRN-42"
    ds.StudyDate = "20240110"
    ds.PatientBirthDate = "19800315"
    ds.AccessionNumber = "ACC123"
    ds.ReferringPhysicianName = "Smith^John"
    p = Pseudonymizer(SECRET, "ns")
    orig_study_uid = ds.StudyInstanceUID

    out, warnings = deidentify_dataset(ds, p, "MRN-42")

    assert out.PatientID == p.pseudonym("MRN-42") and str(out.PatientName) == p.pseudonym("MRN-42")
    assert "AccessionNumber" not in out and "ReferringPhysicianName" not in out
    assert out.StudyInstanceUID != orig_study_uid and out.StudyInstanceUID == p.uid(orig_study_uid)
    assert out.file_meta.MediaStorageSOPInstanceUID == out.SOPInstanceUID
    assert out.PatientBirthDate.endswith("0101")
    shifted = out.StudyDate
    assert shifted != "20240110" and len(shifted) == 8
    assert out.PatientIdentityRemoved == "YES" and "113100" in [c.CodeValue for c in out.DeidentificationMethodCodeSequence]
    assert not [e for e in out if e.tag.is_private]
    assert warnings == []


def test_flat_deid_shifts_dates_and_redacts_text():
    p = Pseudonymizer(SECRET, "ns")
    flat = {
        "t/context/start_time": "2024-01-10T09:30:00Z",
        "t/composer|name": "Dr. Kim",
        "t/obs/any_event:0/comment": "Call Dr. Smith at 010-1234-5678, mrn 123456-1234567",
        "t/obs/any_event:0/modality|code": "CT",
        "t/obs/any_event:0/modality|value": "CT",
    }
    out, warnings = deidentify_flat(flat, p, "MRN-42")
    assert "t/composer|name" not in out
    assert out["t/context/start_time"] != flat["t/context/start_time"]
    assert "[PHONE]" in out["t/obs/any_event:0/comment"] and "[ID]" in out["t/obs/any_event:0/comment"]
    assert "Smith" not in out["t/obs/any_event:0/comment"]
    assert out["t/obs/any_event:0/modality|value"] == "CT"      # coded text untouched
    assert warnings
