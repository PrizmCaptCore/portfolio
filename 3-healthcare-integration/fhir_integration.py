"""FHIR R4 healthcare data integration for medical imaging workflows."""

import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from google.cloud import healthcare_v1
import aiohttp


@dataclass
class PatientContext:
    """Patient context for medical imaging workflow."""
    patient_id: str
    mrn: str  # Medical Record Number
    name: str
    birth_date: str
    gender: str


class FHIRIntegrationService:
    """Service for integrating medical imaging with FHIR EHR data."""

    def __init__(
        self,
        project_id: str,
        location: str,
        dataset_id: str,
        fhir_store_id: str
    ):
        self.project_id = project_id
        self.location = location
        self.dataset_id = dataset_id
        self.fhir_store_id = fhir_store_id
        self.client = healthcare_v1.FhirServiceClient()
        self._setup_paths()

    def _setup_paths(self):
        """Setup FHIR store paths."""
        self.fhir_store_path = (
            f"projects/{self.project_id}/"
            f"locations/{self.location}/"
            f"datasets/{self.dataset_id}/"
            f"fhirStores/{self.fhir_store_id}"
        )

    async def get_patient_demographics(self, patient_id: str) -> PatientContext:
        """
        Retrieve patient demographics from FHIR.

        Args:
            patient_id: FHIR Patient resource ID

        Returns:
            Patient demographic information
        """
        resource_path = f"{self.fhir_store_path}/fhir/Patient/{patient_id}"
        request = healthcare_v1.GetFhirResourceRequest(name=resource_path)

        response = await asyncio.to_thread(
            self.client.get_fhir_resource,
            request=request
        )

        patient_data = response.data

        return PatientContext(
            patient_id=patient_id,
            mrn=patient_data.get('identifier', [{}])[0].get('value', ''),
            name=self._format_name(patient_data.get('name', [{}])[0]),
            birth_date=patient_data.get('birthDate', ''),
            gender=patient_data.get('gender', '')
        )

    def _format_name(self, name_data: Dict) -> str:
        """Format FHIR HumanName to string."""
        given = ' '.join(name_data.get('given', []))
        family = name_data.get('family', '')
        return f"{given} {family}".strip()

    async def get_imaging_studies(
        self,
        patient_id: str,
        modality: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve imaging studies for a patient.

        Args:
            patient_id: FHIR Patient ID
            modality: Optional modality filter (CT, MRI, etc.)

        Returns:
            List of ImagingStudy resources
        """
        query_params = {"patient": patient_id}
        if modality:
            query_params["modality"] = modality

        query_string = "&".join(f"{k}={v}" for k, v in query_params.items())

        request = healthcare_v1.SearchFhirResourcesRequest(
            parent=self.fhir_store_path,
            resource_type="ImagingStudy",
            query_string=query_string
        )

        response = await asyncio.to_thread(
            self.client.search_fhir_resources,
            request=request
        )

        return [self._parse_imaging_study(res.resource) for res in response.resources]

    def _parse_imaging_study(self, study: Dict) -> Dict[str, Any]:
        """Parse ImagingStudy resource."""
        return {
            "study_id": study.get("id"),
            "study_uid": study.get("identifier", [{}])[0].get("value"),
            "started": study.get("started"),
            "modality": study.get("modality", [{}])[0].get("code"),
            "description": study.get("description", ""),
            "series_count": len(study.get("series", []))
        }

    async def create_diagnostic_report(
        self,
        patient_id: str,
        imaging_study_id: str,
        findings: Dict[str, Any],
        performer_id: str
    ) -> str:
        """
        Create FHIR DiagnosticReport for imaging analysis.

        Args:
            patient_id: Patient ID
            imaging_study_id: ImagingStudy ID
            findings: Analysis findings from ML model
            performer_id: Practitioner ID

        Returns:
            Created DiagnosticReport ID
        """
        report = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                    "code": "RAD",
                    "display": "Radiology"
                }]
            }],
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "24604-1",
                    "display": "MG Diagnostic Study"
                }]
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "effectiveDateTime": datetime.utcnow().isoformat(),
            "issued": datetime.utcnow().isoformat(),
            "performer": [{
                "reference": f"Practitioner/{performer_id}"
            }],
            "imagingStudy": [{
                "reference": f"ImagingStudy/{imaging_study_id}"
            }],
            "conclusion": findings.get("conclusion", ""),
            "conclusionCode": self._map_findings_to_codes(findings)
        }

        request = healthcare_v1.CreateFhirResourceRequest(
            parent=self.fhir_store_path,
            type_="DiagnosticReport",
            body=str(report).encode("utf-8")
        )

        response = await asyncio.to_thread(
            self.client.create_fhir_resource,
            request=request
        )

        return response.data.get("id")

    def _map_findings_to_codes(self, findings: Dict) -> List[Dict]:
        """Map ML findings to SNOMED CT codes."""
        code_mapping = {
            "normal": "17621005",
            "abnormal": "263654008",
            "malignant": "363346000"
        }

        codes = []
        for finding, present in findings.items():
            if present and finding in code_mapping:
                codes.append({
                    "coding": [{
                        "system": "http://snomed.info/sct",
                        "code": code_mapping[finding],
                        "display": finding.capitalize()
                    }]
                })

        return codes

    async def get_relevant_observations(
        self,
        patient_id: str,
        observation_codes: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Get relevant clinical observations for context.

        Args:
            patient_id: Patient ID
            observation_codes: LOINC codes for observations

        Returns:
            List of Observation resources
        """
        observations = []

        for code in observation_codes:
            query_string = f"patient={patient_id}&code={code}"

            request = healthcare_v1.SearchFhirResourcesRequest(
                parent=self.fhir_store_path,
                resource_type="Observation",
                query_string=query_string
            )

            response = await asyncio.to_thread(
                self.client.search_fhir_resources,
                request=request
            )

            observations.extend([
                self._parse_observation(res.resource)
                for res in response.resources
            ])

        return observations

    def _parse_observation(self, obs: Dict) -> Dict[str, Any]:
        """Parse Observation resource."""
        value = obs.get("valueQuantity", {})
        return {
            "observation_id": obs.get("id"),
            "code": obs.get("code", {}).get("coding", [{}])[0].get("code"),
            "display": obs.get("code", {}).get("text", ""),
            "value": value.get("value"),
            "unit": value.get("unit"),
            "effective_date": obs.get("effectiveDateTime", "")
        }


async def process_imaging_workflow(
    fhir_service: FHIRIntegrationService,
    patient_id: str,
    study_id: str,
    ml_findings: Dict[str, Any]
):
    """
    Complete workflow: Retrieve patient data, process imaging, create report.

    Args:
        fhir_service: FHIR integration service
        patient_id: Patient ID
        study_id: ImagingStudy ID
        ml_findings: ML model findings
    """
    # Get patient demographics
    patient = await fhir_service.get_patient_demographics(patient_id)
    print(f"Processing imaging for patient: {patient.name} (MRN: {patient.mrn})")

    # Get relevant clinical context
    relevant_codes = ["8480-6", "29463-7"]  # BP systolic, body weight
    observations = await fhir_service.get_relevant_observations(
        patient_id,
        relevant_codes
    )
    print(f"Retrieved {len(observations)} relevant observations")

    # Create diagnostic report
    report_id = await fhir_service.create_diagnostic_report(
        patient_id=patient_id,
        imaging_study_id=study_id,
        findings=ml_findings,
        performer_id="ai-system-001"
    )

    print(f"Created DiagnosticReport: {report_id}")

    return {
        "patient": patient,
        "observations": observations,
        "report_id": report_id
    }


if __name__ == "__main__":
    # Example usage
    service = FHIRIntegrationService(
        project_id="my-healthcare-project",
        location="us-central1",
        dataset_id="healthcare-dataset",
        fhir_store_id="fhir-store"
    )

    ml_findings = {
        "conclusion": "No significant abnormalities detected",
        "normal": True,
        "abnormal": False,
        "confidence": 0.94
    }

    asyncio.run(
        process_imaging_workflow(
            fhir_service=service,
            patient_id="patient-12345",
            study_id="study-67890",
            ml_findings=ml_findings
        )
    )
