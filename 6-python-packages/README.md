# Python ML Packages

Production Python packages for ML workflows - demonstrating monorepo architecture and modern packaging practices.

## Overview

Developed 16+ Python packages in a monorepo structure for:
- Medical image preprocessing and inference
- FHIR/DICOM data handling
- ML pipeline utilities
- Report generation and validation

## Package Structure

```
packages/
├── ml_inference/           # ML model inference SDK
├── dicom_processor/        # DICOM preprocessing utilities
├── fhir_client/           # FHIR R4 API client
├── report_generator/      # Medical report generation
└── pipeline_utils/        # Shared pipeline utilities
```

## Example 1: ML Inference Package

**File**: `packages/ml_inference/pyproject.toml`
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "ml-inference"
version = "1.2.3"
description = "Production ML inference SDK for medical imaging"
requires-python = ">=3.9"
dependencies = [
    "torch>=2.0.0",
    "torchvision>=0.15.0",
    "numpy>=1.23.0",
    "pillow>=9.0.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0.0", "pytest-asyncio>=0.21.0", "black", "mypy"]
```

**File**: `packages/ml_inference/src/ml_inference/inference.py`
```python
"""ML model inference engine with preprocessing pipeline."""

from pathlib import Path
from typing import Optional, Dict, Any
import torch
import numpy as np
from pydantic import BaseModel, Field


class InferenceConfig(BaseModel):
    """Configuration for inference engine."""
    model_path: Path
    device: str = Field(default="cuda" if torch.cuda.is_available() else "cpu")
    batch_size: int = Field(default=8, gt=0)
    num_workers: int = Field(default=4, ge=0)


class ModelInference:
    """Production inference engine for PyTorch models."""

    def __init__(self, config: InferenceConfig):
        self.config = config
        self.device = torch.device(config.device)
        self.model = self._load_model()

    def _load_model(self) -> torch.nn.Module:
        """Load and prepare model for inference."""
        model = torch.jit.load(str(self.config.model_path))
        model.to(self.device)
        model.eval()
        return model

    @torch.no_grad()
    def predict(self, input_data: np.ndarray) -> Dict[str, Any]:
        """
        Run inference on input data.

        Args:
            input_data: Preprocessed numpy array (C, H, W)

        Returns:
            Dictionary with predictions and confidence scores
        """
        # Convert to tensor
        tensor = torch.from_numpy(input_data).float()
        tensor = tensor.unsqueeze(0).to(self.device)

        # Run inference
        output = self.model(tensor)

        # Post-process results
        probabilities = torch.softmax(output, dim=1)
        prediction = torch.argmax(probabilities, dim=1)
        confidence = torch.max(probabilities, dim=1).values

        return {
            "prediction": prediction.cpu().item(),
            "confidence": confidence.cpu().item(),
            "probabilities": probabilities.cpu().numpy().tolist()
        }

    def predict_batch(self, batch: list[np.ndarray]) -> list[Dict[str, Any]]:
        """Batch inference for multiple inputs."""
        return [self.predict(data) for data in batch]
```

## Example 2: DICOM Processor Package

**File**: `packages/dicom_processor/src/dicom_processor/preprocessor.py`
```python
"""DICOM image preprocessing utilities."""

import numpy as np
import pydicom
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class PreprocessConfig:
    """Preprocessing configuration."""
    target_size: Tuple[int, int] = (512, 512)
    normalize: bool = True
    apply_windowing: bool = True
    window_center: Optional[float] = None
    window_width: Optional[float] = None


class DICOMPreprocessor:
    """DICOM image preprocessing pipeline."""

    def __init__(self, config: PreprocessConfig):
        self.config = config

    def load_dicom(self, path: Path) -> pydicom.Dataset:
        """Load DICOM file."""
        return pydicom.dcmread(str(path))

    def apply_windowing(
        self,
        pixel_array: np.ndarray,
        center: float,
        width: float
    ) -> np.ndarray:
        """Apply DICOM windowing (contrast adjustment)."""
        img_min = center - width // 2
        img_max = center + width // 2
        windowed = np.clip(pixel_array, img_min, img_max)
        return windowed

    def normalize(self, pixel_array: np.ndarray) -> np.ndarray:
        """Normalize pixel values to [0, 1]."""
        pixel_array = pixel_array.astype(np.float32)
        return (pixel_array - pixel_array.min()) / (
            pixel_array.max() - pixel_array.min() + 1e-8
        )

    def resize(
        self,
        pixel_array: np.ndarray,
        target_size: Tuple[int, int]
    ) -> np.ndarray:
        """Resize image to target dimensions."""
        from PIL import Image
        img = Image.fromarray(pixel_array)
        img = img.resize(target_size, Image.BILINEAR)
        return np.array(img)

    def preprocess(self, dicom_path: Path) -> np.ndarray:
        """
        Complete preprocessing pipeline.

        Args:
            dicom_path: Path to DICOM file

        Returns:
            Preprocessed numpy array ready for ML inference
        """
        # Load DICOM
        dcm = self.load_dicom(dicom_path)
        pixel_array = dcm.pixel_array.astype(np.float32)

        # Apply windowing if configured
        if self.config.apply_windowing:
            center = self.config.window_center or dcm.WindowCenter
            width = self.config.window_width or dcm.WindowWidth
            pixel_array = self.apply_windowing(pixel_array, center, width)

        # Normalize
        if self.config.normalize:
            pixel_array = self.normalize(pixel_array)

        # Resize
        pixel_array = self.resize(pixel_array, self.config.target_size)

        return pixel_array
```

## Example 3: FHIR Client Package

**File**: `packages/fhir_client/src/fhir_client/client.py`
```python
"""FHIR R4 API client for healthcare data integration."""

import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import aiohttp
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
```

## Example 4: Monorepo Configuration

**File**: `pyproject.toml` (Root)
```toml
[tool.pytest.ini_options]
testpaths = ["packages/*/tests"]
pythonpath = [
    "packages/ml_inference/src",
    "packages/dicom_processor/src",
    "packages/fhir_client/src",
]

[tool.black]
line-length = 88
target-version = ['py39', 'py310', 'py311']
include = '\.pyi?$'

[tool.isort]
profile = "black"
multi_line_output = 3

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
```

**File**: `.pre-commit-config.yaml`
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3.9

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/charliermarsh/ruff-pre-commit
    rev: v0.0.272
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
```

## Key Design Patterns

### 1. Configuration Management
- Use Pydantic models for type-safe configs
- Environment-based configuration
- Validation at load time

### 2. Async/Await Pattern
- Async I/O for API calls
- Concurrent batch processing
- Non-blocking medical data pipelines

### 3. Error Handling
```python
from typing import Union
from pydantic import ValidationError

try:
    result = await client.get_patient(patient_id)
except ValidationError as e:
    logger.error(f"Invalid patient data: {e}")
    raise
except Exception as e:
    logger.error(f"API error: {e}")
    # Retry logic or fallback
```

### 4. Testing Strategy
```python
# tests/test_inference.py
import pytest
from ml_inference import ModelInference, InferenceConfig

@pytest.fixture
def mock_model(tmp_path):
    model_path = tmp_path / "model.pt"
    # Create mock model
    return model_path

@pytest.mark.asyncio
async def test_inference_pipeline(mock_model):
    config = InferenceConfig(model_path=mock_model)
    inference = ModelInference(config)

    # Test inference
    result = inference.predict(test_data)
    assert "prediction" in result
    assert 0 <= result["confidence"] <= 1
```

## Technologies Used

- **Core**: Python 3.9+, Type hints, Dataclasses, Pydantic
- **ML**: PyTorch, TorchVision, MONAI
- **Medical**: Pydicom, nibabel, SimpleITK
- **Healthcare APIs**: Google Cloud Healthcare API, FHIR R4
- **Async**: asyncio, aiohttp
- **Testing**: pytest, pytest-asyncio, pytest-cov
- **Code Quality**: Black, isort, mypy, ruff, pre-commit

---

**Note**: All code samples are simplified and anonymized. Proprietary business logic, model architectures, and domain-specific implementations have been removed.
