"""PACS/DICOM integration client for medical imaging retrieval and storage."""

from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelFind
)
from pydicom.dataset import Dataset
import pydicom
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PACSConfig:
    """PACS server configuration."""
    host: str
    port: int
    aet: str  # Application Entity Title
    calling_aet: str = "MLOPS_CLIENT"
    timeout: int = 30


class PACSClient:
    """Client for DICOM Query/Retrieve operations with PACS."""

    def __init__(self, config: PACSConfig):
        self.config = config
        self.ae = AE(ae_title=config.calling_aet)

        # Add requested presentation contexts
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)

        # Add storage contexts for C-STORE
        for context in StoragePresentationContexts:
            self.ae.add_requested_context(context.abstract_syntax)

    def find_studies(
        self,
        patient_id: Optional[str] = None,
        patient_name: Optional[str] = None,
        study_date: Optional[str] = None,
        modality: Optional[str] = None
    ) -> List[Dataset]:
        """
        Query PACS for studies matching criteria.

        Args:
            patient_id: Patient ID
            patient_name: Patient name (can use wildcards)
            study_date: Study date (YYYYMMDD or range YYYYMMDD-YYYYMMDD)
            modality: Modality (CT, MRI, CR, etc.)

        Returns:
            List of matching study datasets
        """
        # Create query dataset
        ds = Dataset()
        ds.QueryRetrieveLevel = 'STUDY'
        ds.PatientID = patient_id or ''
        ds.PatientName = patient_name or ''
        ds.StudyDate = study_date or ''
        ds.Modality = modality or ''

        # Required return attributes
        ds.StudyInstanceUID = ''
        ds.StudyDescription = ''
        ds.StudyDate = ''
        ds.StudyTime = ''
        ds.AccessionNumber = ''
        ds.NumberOfStudyRelatedSeries = ''
        ds.NumberOfStudyRelatedInstances = ''

        results = []

        # Associate with PACS
        assoc = self.ae.associate(
            self.config.host,
            self.config.port,
            ae_title=self.config.aet
        )

        if assoc.is_established:
            # Send C-FIND request
            responses = assoc.send_c_find(
                ds,
                PatientRootQueryRetrieveInformationModelFind
            )

            for (status, identifier) in responses:
                if status and status.Status in (0xFF00, 0xFF01):
                    # Pending status - result available
                    results.append(identifier)

            assoc.release()
            logger.info(f"Found {len(results)} studies")
        else:
            logger.error("Failed to associate with PACS")

        return results

    def find_series(self, study_instance_uid: str) -> List[Dataset]:
        """
        Query for series within a study.

        Args:
            study_instance_uid: Study Instance UID

        Returns:
            List of series datasets
        """
        ds = Dataset()
        ds.QueryRetrieveLevel = 'SERIES'
        ds.StudyInstanceUID = study_instance_uid
        ds.SeriesInstanceUID = ''
        ds.SeriesNumber = ''
        ds.SeriesDescription = ''
        ds.Modality = ''
        ds.NumberOfSeriesRelatedInstances = ''

        results = []

        assoc = self.ae.associate(
            self.config.host,
            self.config.port,
            ae_title=self.config.aet
        )

        if assoc.is_established:
            responses = assoc.send_c_find(
                ds,
                PatientRootQueryRetrieveInformationModelFind
            )

            for (status, identifier) in responses:
                if status and status.Status in (0xFF00, 0xFF01):
                    results.append(identifier)

            assoc.release()
            logger.info(f"Found {len(results)} series in study")

        return results

    def retrieve_study(
        self,
        study_instance_uid: str,
        destination_aet: str,
        destination_path: Path
    ) -> bool:
        """
        Retrieve study from PACS using C-MOVE.

        Args:
            study_instance_uid: Study to retrieve
            destination_aet: Destination AE title
            destination_path: Local path to store files

        Returns:
            Success status
        """
        destination_path.mkdir(parents=True, exist_ok=True)

        # Setup storage SCP to receive images
        handlers = [(evt.EVT_C_STORE, self._handle_store, [destination_path])]

        # Start SCP in background
        self.ae.add_supported_context(StoragePresentationContexts)
        scp = self.ae.start_server(
            ('', 11112),
            block=False,
            evt_handlers=handlers
        )

        # Perform C-MOVE
        ds = Dataset()
        ds.QueryRetrieveLevel = 'STUDY'
        ds.StudyInstanceUID = study_instance_uid

        assoc = self.ae.associate(
            self.config.host,
            self.config.port,
            ae_title=self.config.aet
        )

        if assoc.is_established:
            responses = assoc.send_c_move(
                ds,
                destination_aet,
                PatientRootQueryRetrieveInformationModelMove
            )

            for (status, identifier) in responses:
                if status:
                    logger.info(
                        f"C-MOVE status: {status.Status:04x} "
                        f"({status.NumberOfCompletedSuboperations}/"
                        f"{status.NumberOfRemainingSuboperations})"
                    )

            assoc.release()
            success = True
        else:
            logger.error("Failed to establish association for C-MOVE")
            success = False

        scp.shutdown()
        return success

    def _handle_store(self, event, storage_path: Path):
        """Handle incoming C-STORE request."""
        ds = event.dataset
        ds.file_meta = event.file_meta

        # Generate filename
        sop_instance_uid = ds.SOPInstanceUID
        filename = storage_path / f"{sop_instance_uid}.dcm"

        # Save DICOM file
        ds.save_as(filename, write_like_original=False)
        logger.info(f"Stored: {filename}")

        return 0x0000  # Success

    def send_to_pacs(self, dicom_file: Path) -> bool:
        """
        Send DICOM file to PACS using C-STORE.

        Args:
            dicom_file: Path to DICOM file

        Returns:
            Success status
        """
        ds = pydicom.dcmread(str(dicom_file))

        assoc = self.ae.associate(
            self.config.host,
            self.config.port,
            ae_title=self.config.aet
        )

        if assoc.is_established:
            status = assoc.send_c_store(ds)

            if status and status.Status == 0x0000:
                logger.info(f"Successfully sent {dicom_file}")
                success = True
            else:
                logger.error(f"Failed to send {dicom_file}")
                success = False

            assoc.release()
        else:
            logger.error("Failed to associate with PACS")
            success = False

        return success


def extract_study_metadata(study: Dataset) -> Dict[str, Any]:
    """Extract relevant metadata from study dataset."""
    return {
        "study_uid": getattr(study, 'StudyInstanceUID', ''),
        "study_date": getattr(study, 'StudyDate', ''),
        "study_time": getattr(study, 'StudyTime', ''),
        "study_description": getattr(study, 'StudyDescription', ''),
        "accession_number": getattr(study, 'AccessionNumber', ''),
        "patient_id": getattr(study, 'PatientID', ''),
        "patient_name": str(getattr(study, 'PatientName', '')),
        "modality": getattr(study, 'Modality', ''),
        "num_series": getattr(study, 'NumberOfStudyRelatedSeries', 0),
        "num_instances": getattr(study, 'NumberOfStudyRelatedInstances', 0)
    }


if __name__ == "__main__":
    # Example usage
    config = PACSConfig(
        host="pacs.hospital.local",
        port=11112,
        aet="PACS_SERVER",
        calling_aet="MLOPS_CLIENT"
    )

    client = PACSClient(config)

    # Query for studies
    studies = client.find_studies(
        patient_id="12345",
        study_date="20240101-20240131",
        modality="CT"
    )

    for study in studies:
        metadata = extract_study_metadata(study)
        print(f"Study: {metadata['study_description']}")
        print(f"  Date: {metadata['study_date']}")
        print(f"  Series: {metadata['num_series']}")
        print(f"  Instances: {metadata['num_instances']}")

        # Retrieve study
        if metadata['study_uid']:
            client.retrieve_study(
                study_instance_uid=metadata['study_uid'],
                destination_aet="MLOPS_CLIENT",
                destination_path=Path(f"/tmp/studies/{metadata['study_uid']}")
            )
