"""FHIR R4 API client for healthcare data integration."""

import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from google.cloud import healthcare_v1


@dataclass
class FHIRConfig:
    """FHIR server configuration."""
    project_id: str
    location: str
    dataset_id: str
    fhir_store_id: str
    base_url: Optional[str] = None


class FHIRClient:
    """Async FHIR R4 client for GCP Healthcare API."""

    def __init__(self, config: FHIRConfig):
        self.config = config
        self.client = healthcare_v1.FhirServiceClient()
        self._setup_paths()

    def _setup_paths(self):
        """Setup FHIR store paths."""
        self.fhir_store_path = (
            f"projects/{self.config.project_id}/"
            f"locations/{self.config.location}/"
            f"datasets/{self.config.dataset_id}/"
            f"fhirStores/{self.config.fhir_store_id}"
        )

    async def get_patient(self, patient_id: str) -> Dict[str, Any]:
        """
        Retrieve patient resource by ID.

        Args:
            patient_id: FHIR patient resource ID

        Returns:
            FHIR Patient resource as dictionary
        """
        resource_path = f"{self.fhir_store_path}/fhir/Patient/{patient_id}"
        request = healthcare_v1.GetFhirResourceRequest(name=resource_path)

        response = await asyncio.to_thread(
            self.client.get_fhir_resource, request=request
        )

        return response.data

    async def search_observations(
        self,
        patient_id: str,
        code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search observation resources for a patient.

        Args:
            patient_id: Patient ID to search for
            code: Optional LOINC/SNOMED code filter

        Returns:
            List of Observation resources
        """
        search_path = f"{self.fhir_store_path}/fhir/Observation"
        params = {"patient": patient_id}
        if code:
            params["code"] = code

        request = healthcare_v1.SearchFhirResourcesRequest(
            parent=self.fhir_store_path,
            resource_type="Observation",
            query_string="&".join(f"{k}={v}" for k, v in params.items())
        )

        response = await asyncio.to_thread(
            self.client.search_fhir_resources, request=request
        )

        return [entry.resource for entry in response.resources]

    async def create_diagnostic_report(
        self,
        patient_id: str,
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a FHIR DiagnosticReport resource."""
        report = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "subject": {"reference": f"Patient/{patient_id}"},
            "conclusion": results.get("conclusion", ""),
            "result": results.get("observations", [])
        }

        # Create resource request
        request = healthcare_v1.CreateFhirResourceRequest(
            parent=self.fhir_store_path,
            type_="DiagnosticReport",
            body=str(report).encode("utf-8")
        )

        response = await asyncio.to_thread(
            self.client.create_fhir_resource, request=request
        )

        return response.data
