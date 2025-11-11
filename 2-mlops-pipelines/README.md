# MLOps Pipelines

Production ML pipeline orchestration with ClearML, Airflow, and AWS Spot instances.

## Components

### 1. ClearML Pipeline ([clearml_pipeline.py](clearml_pipeline.py))
End-to-end ML training pipeline with:
- Function-based pipeline steps
- Data preprocessing → Training → Evaluation → Deployment
- XCom-like parameter passing between steps
- Cache-enabled steps for efficiency
- Remote execution support

**Key Features:**
- Pydantic-based configuration
- Automatic dependency management
- MLflow integration for experiment tracking
- Production deployment automation

### 2. AWS Spot Autoscaler ([spot_autoscaler.py](spot_autoscaler.py))
Dynamic EC2 Spot instance management for ClearML agents:
- Queue-based scaling logic
- Automatic instance provisioning/termination
- Cost optimization: ~60% savings vs on-demand
- Configurable min/max instances
- User data script for agent setup

**Scaling Logic:**
- Scale up: When queue length exceeds threshold
- Scale down: When instances idle beyond timeout
- Health checks: Monitor agent activity

### 3. Airflow DAG ([airflow_dag.py](airflow_dag.py))
Production ML workflow with:
- S3 data ingestion
- Multi-stage preprocessing
- Model training and evaluation
- Quality gates (accuracy threshold)
- S3 artifact storage
- Deployment trigger

**Pipeline Stages:**
1. Download data from S3
2. Preprocess and feature engineering
3. Train ML model
4. Evaluate with metrics
5. Upload to model registry
6. Trigger deployment

## Architecture

```
┌─────────────────┐
│  Airflow DAG    │
│  (Orchestrator) │
└────────┬────────┘
         │
    ┌────▼────┐
    │ S3 Data │
    └────┬────┘
         │
    ┌────▼──────────┐
    │ ClearML Queue │
    └────┬──────────┘
         │
    ┌────▼────────────────┐
    │ Spot Autoscaler     │
    │ (EC2 Management)    │
    └────┬────────────────┘
         │
    ┌────▼────────┐
    │ ClearML     │
    │ Agents (GPU)│
    └────┬────────┘
         │
    ┌────▼────────┐
    │ MLflow      │
    │ (Tracking)  │
    └─────────────┘
```

## Usage

### Running ClearML Pipeline
```python
from clearml_pipeline import create_ml_pipeline

pipeline = create_ml_pipeline(
    project_name="MLOps-Pipeline",
    pipeline_name="Training-Pipeline"
)

pipeline.add_parameter("dataset_id", "dataset-12345")
pipeline.start_remotely(queue_name="gpu-queue")
```

### Starting Spot Autoscaler
```python
from spot_autoscaler import SpotInstanceAutoscaler, AutoscalerConfig

config = AutoscalerConfig(
    region="us-east-1",
    instance_type="g4dn.xlarge",
    queue_name="gpu-training",
    min_instances=0,
    max_instances=5
)

autoscaler = SpotInstanceAutoscaler(config, clearml_api_key="...")
autoscaler.run()
```

### Deploying Airflow DAG
```bash
# Copy DAG to Airflow dags folder
cp airflow_dag.py /opt/airflow/dags/

# Trigger manually
airflow dags trigger ml_training_pipeline

# Check status
airflow dags list-runs ml_training_pipeline
```

## Cost Optimization Results

| Instance Type | On-Demand | Spot | Savings |
|--------------|-----------|------|---------|
| g4dn.xlarge  | $0.526/hr | $0.21/hr | 60% |
| p3.2xlarge   | $3.06/hr  | $1.22/hr | 60% |
| p3.8xlarge   | $12.24/hr | $4.90/hr | 60% |

## Technologies

- **ClearML**: Pipeline orchestration, experiment tracking
- **Airflow**: Workflow scheduling, DAG management
- **AWS Boto3**: EC2 Spot instance management
- **MLflow**: Experiment tracking, model registry
- **Python**: asyncio, dataclasses, type hints

