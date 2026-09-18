# 김조민 (Jomin Kim) — Engineering Portfolio

**AI 제품 엔지니어링 · MLOps · 클라우드 인프라 · 헬스케어 IT.**
실시간 음성 AI 제품(데스크톱 오디오 파이프라인부터 비용 튜닝된 GPU 서빙, 커스텀 ASR 학습까지)을 혼자서
풀스택으로 구축한 경험과, 프로덕션 MLOps/인프라·엣지 비전 역량을 함께 담았습니다.

Production-grade AI product engineering, MLOps infrastructure, and healthcare data pipelines —
showcasing Rust/Tauri real-time speech, vLLM GPU serving, custom ASR training, AWS, Kubernetes,
Terraform, and Python.

## Overview

This portfolio demonstrates hands-on experience in:
- **AI Product Engineering**: 실시간 음성(Tauri/Rust 오디오 파이프라인 + 스트리밍 STT), vLLM/NeMo GPU 서빙, 커스텀 한국어 ASR, 회의 지식그래프
- **Edge Vision & Deployment**: GigE 멀티카메라 수집, NanoDet 선별 판정, NHN Cloud Terraform + Nuitka 온프레미스 패키징
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

### 3. [Orthanc + openEHR 통합 · 가명화 브리지](./3-healthcare-integration/)
DICOM(Orthanc)과 임상 기록(EHRbase/openEHR)을 하나의 비식별화 정책으로 잇는 통합 레포:
- docker-compose 로 식별/가명 Orthanc 2대 + EHRbase + 브리지 기동, 식별 데이터는 source 밖으로 나가지 않음
- HMAC 가명 + 환자별 날짜 시프트 + UID 재매핑을 DICOM(PS3.15 Basic Profile)과 openEHR composition 에 동일 적용
- StableStudy 기반 멱등 파이프라인, 번인 텍스트 격리, 재식별 vault(가명화)와 vault 없음(익명화)을 같은 코드로

**Technologies**: Orthanc (DICOMweb), EHRbase (openEHR REST/AQL/FLAT), pydicom, httpx, Docker Compose

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
- FastSurfer ↔ FreeSurfer 비교·선별·파인튜닝 파이프라인 (`fastsurfer_finetune`, 재구성 스케치)

**Technologies**: Python, setuptools, pyproject.toml, pytest, FastSurfer/FreeSurfer, nibabel, PyTorch

---

## AI 제품 엔지니어링 — Relay (제품명 익명화)

실시간 회의 인텔리전스 제품 한 개를 데스크톱 클라이언트부터 GPU 추론 백엔드, 커스텀 ASR
모델, 웹 플랫폼, 지식그래프 엔진까지 **전 계층을 직접** 설계·구현했습니다. 아래는 그 서브시스템들이며,
제품/조직명·인프라 좌표·자격증명·비용 수치·고객 데이터는 제거했습니다.

### 7. [실시간 회의 어시스턴트 데스크톱 클라이언트](./7-realtime-asr-desktop/)
Tauri 2 + Rust 코어 + Next.js 웹뷰, 전체 소스:
- 마이크/시스템 오디오 독립 캡처(macOS CoreAudio tap) → RNNoise·R128·리샘플·RMS 게이트 → Silero VAD 발화 분할
- 게이트웨이 서명 세션으로 STT WebSocket(f32 PCM) 연결, LCP stable-prefix 로 partial/final 정합 (깜빡임 0)
- sqlx SQLite + sqlite-vec 로컬 RAG, 웹뷰 WASM 임베딩, minisign updater 릴리스

**Technologies**: Rust, Tauri 2, cpal, Silero VAD, nnnoiseless, tokio-tungstenite, sqlx/sqlite-vec, Next.js 14, React, TypeScript

### 8. [비용 튜닝 GPU 서빙 플릿](./8-vllm-gpu-serving/)
STT(CNN STT/NeMo, Realtime STT/vLLM Realtime) · 요약(Gemma 4) · 임베딩(Qwen3) · 번역(TranslateGemma) 워커 5개, 전체 소스:
- duty cycle 기반 토폴로지: 실시간 대기 서비스만 always-on, sparse 워크로드는 scale-to-zero
- ~80GB NeMo 이미지의 zero-rebuild 배포 (vLLM 서브프로세스 유지 + FastAPI 층만 재기동)
- STT 마이크로배처(final 우선, partial backpressure), 계층 인증, INT4 Marlin 양자화 선택, Network Volume 캐시

**Technologies**: vLLM, NVIDIA NeMo, RunPod Serverless/Pod, Docker/BuildKit, GitHub Actions, CUDA, FastAPI, WebSocket

### 9. [한국어 ASR — Parakeet 인코더 전이](./9-korean-asr-training/)
사전학습 영어 encoder 이식 + 2단계 학습으로 한국어 CTC 모델:
- stage 1 encoder freeze(decoder 만) → stage 2 full fine-tune
- 한국어 SentencePiece BPE(4096), 공개 코퍼스(Common Voice 17 gated 직접 다운로드 / FLEURS)
- 길이 버킷팅, 16-bit + grad accumulation, `strict=True` 인코더 이식 검증

**Technologies**: NVIDIA NeMo, PyTorch Lightning, SentencePiece, CTC, transfer learning, huggingface_hub

### 10. [회의·업무 스트림 지식그래프 엔진](./10-meeting-knowledge-graph/)
채팅/회의 스트림 → single-pass 사건 그래프 (v1 모놀리스 → v3 모듈 리팩터까지 전 이력):
- LLM 은 분류(struct)와 단일 매칭(match)만, EXTEND/BIRTH/PARK 라우팅과 reclaim 은 코드가 결정
- 명시 단서(why/ref hint)에서만 인과 엣지, bounded surface(이름 + 최근 3개)로 토큰 자석 방지
- conflict 는 boolean 판정이 아니라 diff 랭커({reversal|refinement|unrelated, changed})

**Technologies**: Python, Anthropic API, OpenAI 호환 self-hosted LLM, vis-network

### 11. [프로덕션 웹 플랫폼 & 백엔드](./11-web-platform/)
Django + DRF + Celery + React, ECS/CloudFront 배포:
- 마이그레이션 경계를 지키는 아키텍처 테스트(fitness function)
- CDN/컴퓨트 분리를 로컬에서 리허설, 프로덕션과 동일한 async
- 멱등 B2B 일괄 프로비저닝

**Technologies**: Django, DRF, Celery, PostgreSQL, Redis, React/Vite, AWS ECS, CloudFront

### 12. [프로덕션 ECS + CloudFront 인프라](./12-aws-ecs-fargate-cdn/)
단일 CloudFront 진입점 뒤에 SPA(S3)와 API(ECS Fargate)를 함께 두는 Terraform:
- dev/prod 를 같은 모듈로, WAFv2 · OAC · X-Origin-Verify 헤더로 경계 분리
- Fargate Spot 기본, Secrets Manager valueFrom, OIDC 기반 GitHub Actions 배포

**Technologies**: Terraform, AWS (CloudFront, ECS Fargate, ALB, RDS, ElastiCache, WAFv2), GitHub Actions OIDC

### 13. [멀티 타깃 배포 파이프라인](./13-gitops-deploy-pipeline/)
같은 제품 코드를 클라우드 인스턴스와 현장 엣지 디바이스로 내보내는 배포 레포:
- 제품 repo release 태그 → `repository_dispatch` → NHN Cloud(OpenStack 계열) Terraform apply
- 원격 tfstate(S3 호환) + concurrency 그룹, cloud-init 이 제품 repo 의 `deploy/setup.sh` 계약만 실행
- 온프레미스: Nuitka onefile → `.deb`(BuildKit output) / Windows 컨테이너 + MinGW → `.exe`

**Technologies**: Terraform (NHN Cloud provider), GitHub Actions, cloud-init, Docker BuildKit, Nuitka, dpkg

### 14. [Basler GigE 멀티카메라 수집기](./14-multicam-gige-capture/)
Jetson AGX Orin 에서 무인 장시간 녹화를 위한 수집기:
- 시리얼 기준 카메라-설정 바인딩 (열거 순서 비의존), 노드맵 적용 후 재검증
- 디스크 임계값 감시 → writer finalize 후 저장만 중단, GStreamer HW 인코딩(nvv4l2h264enc) 10분 세그먼트

**Technologies**: Python, pypylon, OpenCV(GStreamer), Jetson, GigE Vision

### 15. [산업용 선별기 비전 파이프라인](./15-industrial-sorting-vision/)
컨베이어 위 제품의 정상/불량을 판정하는 엣지 비전의 전체 소스:
- NanoDet-Plus 단일 스테이지 판정, 트랙별 MAX 집계 + `--min-hits` 로 오탐 억제 (mAP 0.69 / AP50 0.90)
- NAS 에서 비디오 1개씩 복사-추출-삭제하는 재시작 안전 라벨링 추출기, 휠 포켓 ghost 정리 도구
- GigE 실측: 스로틀 해제 81.3fps 드랍 0, 고정 버퍼 10분 소크 RSS 플랫, 타 대역 카메라 raw GVCP adoption

**Technologies**: PyTorch, NanoDet, YOLO11, OpenCV, pypylon, Jetson, WSL2

### 16. [회의 요약·인텐트 LLM 파인튜닝](./16-llm-finetune-unsloth/)
8번 서빙 워커의 요약/인텐트 모델을 만든 unsloth LoRA SFT 파이프라인 (원본 유실, 재구성 스케치):
- 체크포인트형 라벨(회의록-so-far → JSON) 데이터셋, 스키마 게이트·meeting 단위 split
- 4-bit 로드 + LoRA r=16, completion-only loss, merged 16-bit 로 vLLM 호환 export
- 계약 평가: JSON 유효율·스키마 적합률·인텐트 정확도·라틴 용어 보존율을 릴리스 게이트로

**Technologies**: unsloth, TRL, PEFT/LoRA, bitsandbytes, Gemma, vLLM

---

## Technical Skills

### AI Product · Speech · LLMOps
- **Real-time Speech**: 스트리밍 STT(WebSocket f32 PCM), Silero VAD, RNNoise/R128 DSP, 채널 분리, partial/final 정합 (Tauri/Rust)
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
