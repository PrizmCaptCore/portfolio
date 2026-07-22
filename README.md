# 김조민 (Jomin Kim) — Engineering Portfolio

**AI 제품 엔지니어링 · MLOps · 클라우드 인프라 · 헬스케어 IT.**
실시간 음성 AI 제품(온디바이스 STT부터 비용 튜닝된 GPU 서빙까지)을 혼자서 풀스택으로 구축한
경험과, 프로덕션 MLOps/인프라 역량을 함께 담았습니다.

Production-grade AI product engineering, MLOps infrastructure, and healthcare data pipelines —
showcasing Rust/Tauri real-time speech, vLLM GPU serving, custom ASR training, AWS, Kubernetes,
Terraform, and Python.

## Overview

This portfolio demonstrates hands-on experience in:
- **AI Product Engineering**: 실시간 음성(Tauri/Rust + 온디바이스 CTC), vLLM GPU 서빙, 커스텀 한국어 ASR, 회의 지식그래프
- **Cloud Infrastructure**: AWS (EC2, S3, IAM, VPC) with Terraform IaC
- **MLOps**: ClearML, Airflow, MLflow pipelines with autoscaling
- **Healthcare Systems**: FHIR R4, PACS/DICOM integration
- **Container Orchestration**: Kubernetes deployments and GitOps
- **HPC**: SLURM cluster setup
- **Python**: Production ML packages and data processing

**Total**: 219+ commits across 12+ production repositories

---

## Projects

### 1. [AWS Terraform Infrastructure](./1-aws-terraform-iac/)
Production-ready Terraform modules for AWS infrastructure:
- EC2 compute with auto-scaling
- IAM roles and policies
- VPC networking and security groups
- ClearML MLOps agent deployment
- Cost-optimized Spot instance management

**Technologies**: Terraform, AWS (EC2, IAM, VPC, CloudWatch), cloud-init

### 2. [MLOps Pipelines](./2-mlops-pipelines/)
End-to-end ML pipeline orchestration:
- ClearML pipeline components
- Airflow DAGs for workflow management
- AWS Spot Instance autoscaler (Boto3)
- MLflow experiment tracking
- Kubernetes deployments

**Technologies**: ClearML, Airflow, MLflow, Boto3, Kubernetes, Python

### 3. [Healthcare Integration Platform](./3-healthcare-integration/)
HIPAA-compliant healthcare system integration:
- FHIR R4 client (GCP Healthcare API)
- PACS/DICOM server integration
- Domain-Driven Design architecture
- Async workflow orchestration

**Technologies**: Python, FHIR R4, DICOM, GCP Healthcare API, Domain-Driven Design

### 4. [Kubernetes GitOps](./4-kubernetes-gitops/)
Production K8s manifests and deployments:
- StatefulSets for PostgreSQL
- Airflow scheduler + webserver
- MLflow tracking server
- ConfigMaps and Secrets management
- Ingress configurations

**Technologies**: Kubernetes, Helm, GitOps, Docker

### 5. [HPC Cluster Setup](./5-hpc-cluster/)
SLURM distributed computing cluster:
- Dockerized SLURM controller and compute nodes
- Munge authentication
- Supervisord process management

**Technologies**: SLURM, Docker, supervisord, HPC

### 6. [Python ML Packages](./6-python-packages/)
Production-ready Python packages for ML workflows:
- Data processing and validation
- ML inference SDKs
- Report generation utilities

**Technologies**: Python, setuptools, pyproject.toml, pytest

---

## AI 제품 엔지니어링 — Relay (제품명 익명화)

실시간 회의 인텔리전스 제품 한 개를 데스크톱 클라이언트부터 GPU 추론 백엔드, 커스텀 ASR
모델, 웹 플랫폼, 지식그래프 엔진까지 **전 계층을 직접** 설계·구현했습니다. 아래는 그 서브시스템들이며,
제품/조직명·인프라 좌표·자격증명·비용 수치·고객 데이터는 제거했습니다.

### 7. [실시간 데스크톱 전사](./7-realtime-asr-desktop/)
Tauri(Rust) 네이티브 앱, 하이브리드 실시간 STT:
- 온디바이스 CTC 로 즉시 partial, 클라우드 모델로 최종 전사 (지연 vs 정확도)
- 마이크/시스템 오디오 채널 분리 + 화자 구분
- VAD·노이즈 억제, 단일 바이너리 배포, 동시 150 세션 검증

**Technologies**: Rust, Tauri, Next.js/React, ONNX Runtime, Parakeet CTC, Pyannote VAD

### 8. [비용 튜닝 vLLM GPU 서빙](./8-vllm-gpu-serving/)
요약/임베딩/번역 vLLM 서빙, duty cycle 기반 토폴로지:
- 실시간 대기 서비스만 always-on, sparse 워크로드는 scale-to-zero
- ~80GB 베이스 이미지의 zero-rebuild(핫리로드) 배포
- 계층 인증, Matryoshka 임베딩 절단, path-filtered CI

**Technologies**: vLLM, Serverless GPU, Docker/BuildKit, GitHub Actions, CUDA

### 9. [한국어 ASR — Parakeet 인코더 전이](./9-korean-asr-training/)
사전학습 영어 encoder 이식 + 2단계 학습으로 한국어 CTC 모델:
- stage 1 encoder freeze(decoder 만) → stage 2 full fine-tune
- 한국어 SentencePiece BPE, 공개 코퍼스(Common Voice/FLEURS)
- loanword 보존 eval 게이트

**Technologies**: NVIDIA NeMo, PyTorch Lightning, SentencePiece, CTC, transfer learning

### 10. [회의 지식그래프 엔진](./10-meeting-knowledge-graph/)
전사 스트림 → 사건 그래프 증분 빌드 (LLM + 결정론적 규칙):
- LLM 은 좁은 분류/매칭만, 그래프 구조(the cut)는 규칙이 결정
- 명시 단서에서만 인과 엣지(환각 방지), 토큰 겹침 prewhere 로 비용 상한
- decision reversal(말 바꿈) 자동 감지

**Technologies**: Python, LLM orchestration, 그래프 모델링, 결정론적 규칙 엔진

### 11. [프로덕션 웹 플랫폼 & 백엔드](./11-web-platform/)
Django + DRF + Celery + React, ECS/CloudFront 배포:
- 마이그레이션 경계를 지키는 아키텍처 테스트(fitness function)
- CDN/컴퓨트 분리를 로컬에서 리허설, 프로덕션과 동일한 async
- 멱등 B2B 일괄 프로비저닝

**Technologies**: Django, DRF, Celery, PostgreSQL, Redis, React/Vite, AWS ECS, CloudFront

---

## Technical Skills

### AI Product · Speech · LLMOps
- **Real-time Speech**: 온디바이스/클라우드 하이브리드 STT, VAD, 채널 분리, 스트리밍 파이프라인 (Tauri/Rust, ONNX Runtime)
- **Model Training**: transfer learning(encoder 이식), 2-stage freeze/fine-tune, SentencePiece, NeMo, PyTorch Lightning
- **LLM Serving (vLLM)**: serverless GPU, always-on vs scale-to-zero 토폴로지, cold-start/비용 최적화, zero-rebuild 배포
- **Applied LLM Systems**: LLM(좁은 판단) + 결정론적 규칙 하이브리드, 임베딩/RAG, 지식그래프

### Cloud & Infrastructure
- **AWS**: EC2, S3, IAM, VPC, CloudWatch, Spot Instances
- **IaC**: Terraform (modules, state management, best practices)
- **Networking**: VPC peering, Transit Gateway, Security Groups

### MLOps & Data Engineering
- **Orchestration**: Airflow, ClearML, MLflow
- **Pipelines**: ETL, ML training/inference workflows
- **Monitoring**: Experiment tracking, metric logging
- **Cost Optimization**: Spot instances, autoscaling

### Container & Kubernetes
- **Kubernetes**: Deployments, StatefulSets, Services, Ingress
- **Docker**: Multi-stage builds, optimization
- **GitOps**: Declarative infrastructure

### Python Development
- **Frameworks**: FastAPI, asyncio, aiohttp
- **ML/Data**: PyTorch, TorchVision, pandas, numpy, scikit-learn, nibabel (medical imaging)
- **Deep Learning**: PyTorch model training/inference, MONAI (medical imaging AI)
- **Data Processing**: Pydicom (DICOM), SimpleITK, medical image preprocessing
- **API Integration**: Google Cloud Healthcare API, FHIR clients, boto3 (AWS SDK)
- **Testing**: pytest, unittest, pytest-asyncio, mocking
- **Packaging**: Monorepo architecture, setuptools, pyproject.toml, namespace packages
- **Code Quality**: Black, isort, mypy, ruff, pre-commit hooks

### Healthcare IT
- **Standards**: FHIR R4, DICOM, HL7
- **Integration**: PACS, EMR/EHR systems
- **Compliance**: HIPAA considerations

---

## Impact & Scale

- **AI Product (end-to-end)**: 실시간 회의 인텔리전스 제품의 전 계층(데스크톱·GPU 서빙·ASR·웹·지식그래프)을 단독 설계·구현
- **Real-time Speech**: 서버측 STT 동시 **150 세션** 실시간 처리 검증
- **GPU Cost Design**: duty cycle 기반 always-on/scale-to-zero 분리로 idle GPU 비용 제거
- **Infrastructure**: Managed AWS environments serving production ML workloads
- **Cost Optimization**: Implemented Spot instance autoscaling reducing compute costs by ~60%
- **Pipelines**: Built end-to-end ML pipelines processing medical imaging data
- **Integration**: Enabled seamless FHIR/DICOM data exchange between healthcare systems
- **Packages**: Developed reusable Python packages deployed across multiple projects

---

## Contact

For inquiries about this portfolio or collaboration opportunities:

- **LinkedIn**: [linkedin.com/in/jomin-kim-643870126](https://www.linkedin.com/in/jomin-kim-643870126)
- **GitHub**: [@PrizmCaptCore](https://github.com/PrizmCaptCore)
- **Email**: lumia82015@live.com · jomin96@gmail.com · 21ghzx86@naver.com

---

## Additional Materials Available on Request

This portfolio showcases production-ready code samples and architecture. Additional materials available upon request for serious inquiries:

### Available Documentation:
- **Detailed AWS Architecture**: Complete dual-VPC Terraform configurations with security group implementations
- **Production MLOps Pipelines**: Full ClearML pipeline code with Spot instance autoscaling
- **Healthcare Integration**: FHIR R4 and PACS/DICOM client implementations
- **Kubernetes Manifests**: Complete GitOps setup for MLOps infrastructure
- **Python Package Source**: Full source code for 16+ production ML packages
- **Architecture Decision Records (ADRs)**: Design decisions and trade-offs
- **Performance Benchmarks**: Cost optimization results and metrics

### How to Request:
Please contact via email or LinkedIn with:
1. Brief introduction of your organization
2. Specific materials you're interested in
3. Intended use case (hiring evaluation, collaboration, etc.)

**Note**: Some implementations contain proprietary architectural patterns and are shared selectively to maintain competitive advantage while demonstrating technical capability.

---

## 📝 License

This portfolio contains anonymized and generalized versions of production code for demonstration purposes. All proprietary business logic has been removed or replaced with generic implementations.
