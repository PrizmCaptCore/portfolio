# MLOps & Cloud Infrastructure Portfolio

Production-grade MLOps infrastructure and healthcare data pipelines showcasing AWS, Kubernetes, Terraform, and Python expertise.

## 📊 Overview

This portfolio demonstrates hands-on experience in:
- **Cloud Infrastructure**: AWS (EC2, S3, IAM, VPC) with Terraform IaC
- **MLOps**: ClearML, Airflow, MLflow pipelines with autoscaling
- **Healthcare Systems**: FHIR R4, PACS/DICOM integration
- **Container Orchestration**: Kubernetes deployments and GitOps
- **HPC**: SLURM cluster setup
- **Python**: Production ML packages and data processing

**Total**: 219+ commits across 12+ production repositories

---

## 🚀 Projects

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

## 💼 Technical Skills

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

## 📈 Impact & Scale

- **Infrastructure**: Managed AWS environments serving production ML workloads
- **Cost Optimization**: Implemented Spot instance autoscaling reducing compute costs by ~60%
- **Pipelines**: Built end-to-end ML pipelines processing medical imaging data
- **Integration**: Enabled seamless FHIR/DICOM data exchange between healthcare systems
- **Packages**: Developed reusable Python packages deployed across multiple projects

---

## 📫 Contact

For inquiries about this portfolio or collaboration opportunities:

- **LinkedIn**: [linkedin.com/in/jomin-kim-643870126](https://www.linkedin.com/in/jomin-kim-643870126)
- **GitHub**: [@PrizmCaptCore](https://github.com/PrizmCaptCore)
- **Email**: lumia82015@live.com

---

## 🔒 Additional Materials Available on Request

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
