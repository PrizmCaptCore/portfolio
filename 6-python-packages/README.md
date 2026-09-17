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
6-python-packages/
├── packages/
│   ├── ml_inference/           # ML model inference SDK
│   │   ├── pyproject.toml
│   │   └── src/ml_inference/
│   │       ├── __init__.py
│   │       └── inference.py
│   ├── dicom_processor/        # DICOM preprocessing utilities
│   │   ├── pyproject.toml
│   │   └── src/dicom_processor/
│   │       ├── __init__.py
│   │       └── preprocessor.py
│   ├── fhir_client/           # FHIR R4 API client
│   │   ├── pyproject.toml
│   │   └── src/fhir_client/
│   │       ├── __init__.py
│   │       └── client.py
│   └── fastsurfer_finetune/   # FastSurfer vs FreeSurfer 비교 → 선별 → FastSurferCNN 파인튜닝 (재구성 스케치)
│       ├── README.md
│       ├── pyproject.toml
│       └── src/fastsurfer_finetune/
│           ├── labels.py, preprocess.py, compare.py, select.py
│           ├── dataset.py, finetune.py, evaluate.py
│           └── cli.py
├── pyproject.toml             # Root config (pytest, black, mypy)
└── .pre-commit-config.yaml    # Code quality hooks
```

## Package Highlights

### 1. ML Inference (`ml_inference`)
Production-ready PyTorch inference engine with:
- Type-safe configuration with Pydantic
- Automatic device selection (CPU/CUDA)
- Batch inference support
- Confidence scoring

**Key file**: [inference.py](packages/ml_inference/src/ml_inference/inference.py)

### 2. DICOM Processor (`dicom_processor`)
Medical image preprocessing pipeline:
- DICOM windowing (contrast adjustment)
- Normalization and resizing
- Production-grade error handling
- Flexible configuration

**Key file**: [preprocessor.py](packages/dicom_processor/src/dicom_processor/preprocessor.py)

### 3. FastSurfer Fine-tune (`fastsurfer_finetune`) — 재구성 스케치
FastSurfer v1 출력을 FreeSurfer recon-all 출력과 구조별 Dice · 부피차 · HD95 로 비교하고, 불일치 케이스만
QC 게이트를 거쳐 라벨로 삼아 FastSurferCNN 을 plane 별로 파인튜닝한 파이프라인
(기준: `feature/one-shot-bias-field` 브랜치):
- 브랜치의 one-shot bias field 보정(CNN 세그를 조직 prior 로 DCT 필드 1회 적합)을 학습 입력 전처리로 재사용
- 피질 라벨은 채점에서 제외 (surface 기반 FreeSurfer 피질은 볼륨 CNN 이 못 맞추는 것이 정상)
- 테스트 셋을 먼저 사이트별 층화로 분리, hard + easy(드리프트 방지) 혼합 학습
- v1 `generate_hdf5` 로 HDF5 생성, `Epoch_30` 체크포인트에서 encoder freeze → 전체 unfreeze, `CombinedLoss`, subcortical Dice 조기 종료
- `Solver` 와 같은 키로 저장해 v1 `eval.py` 의 3-plane view aggregation 결과를 before/after 로 재채점

원본 소스는 남아 있지 않아 FastSurfer 공개 레포(v1.1.x 브랜치) 인터페이스 기준으로 재구성했습니다.

**Key files**: [compare.py](packages/fastsurfer_finetune/src/fastsurfer_finetune/compare.py),
[select.py](packages/fastsurfer_finetune/src/fastsurfer_finetune/select.py),
[finetune.py](packages/fastsurfer_finetune/src/fastsurfer_finetune/finetune.py)

### 4. FHIR Client (`fhir_client`)
Healthcare data integration with FHIR R4:
- Async/await for non-blocking I/O
- GCP Healthcare API integration
- Patient, Observation, DiagnosticReport resources
- Type-safe dataclass configs

**Key file**: [client.py](packages/fhir_client/src/fhir_client/client.py)

## Installation

Each package can be installed independently:

```bash
# Install ML inference package
pip install -e packages/ml_inference

# Install with dev dependencies
pip install -e "packages/ml_inference[dev]"

# Install all packages
pip install -e packages/ml_inference -e packages/dicom_processor -e packages/fhir_client
```

## Usage Examples

### ML Inference
```python
from ml_inference import ModelInference, InferenceConfig
from pathlib import Path

config = InferenceConfig(model_path=Path("model.pt"))
inference = ModelInference(config)

result = inference.predict(image_array)
print(f"Prediction: {result['prediction']}, Confidence: {result['confidence']}")
```

### DICOM Processing
```python
from dicom_processor import DICOMPreprocessor, PreprocessConfig
from pathlib import Path

config = PreprocessConfig(target_size=(512, 512), normalize=True)
processor = DICOMPreprocessor(config)

preprocessed = processor.preprocess(Path("image.dcm"))
```

### FHIR Client
```python
import asyncio
from fhir_client import FHIRClient, FHIRConfig

config = FHIRConfig(
    project_id="my-project",
    location="us-central1",
    dataset_id="healthcare-dataset",
    fhir_store_id="fhir-store"
)
client = FHIRClient(config)

# Async usage
async def get_patient_data():
    patient = await client.get_patient("patient-123")
    observations = await client.search_observations("patient-123")
    return patient, observations

asyncio.run(get_patient_data())
```

## Development

### Setup
```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Run tests
pytest

# Code formatting
black packages/
isort packages/

# Type checking
mypy packages/
```

### Code Quality Tools

- **Black**: Automatic code formatting (88 char line length)
- **isort**: Import sorting compatible with Black
- **mypy**: Static type checking (strict mode)
- **ruff**: Fast Python linter
- **pytest**: Testing framework with async support

## Key Design Patterns

### 1. Configuration Management
Use Pydantic models or dataclasses for type-safe configuration:
```python
from pydantic import BaseModel, Field

class Config(BaseModel):
    model_path: Path
    device: str = Field(default="cpu")
```

### 2. Async/Await Pattern
Non-blocking I/O for API calls and data processing:
```python
async def process_batch(items):
    tasks = [process_item(item) for item in items]
    return await asyncio.gather(*tasks)
```

### 3. Error Handling
Explicit error handling with proper logging:
```python
try:
    result = await client.get_resource(id)
except ValidationError as e:
    logger.error(f"Validation failed: {e}")
    raise
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
