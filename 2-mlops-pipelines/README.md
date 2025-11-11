# MLOps Pipelines

Production ML pipeline orchestration with ClearML, Airflow, and AWS Spot instances.

## Components

- `clearml_pipeline.py` - ClearML pipeline with decorator-based components
- `airflow_dag.py` - Airflow DAG for workflow orchestration  
- `spot_autoscaler.py` - AWS EC2 Spot instance autoscaler (Boto3)
- `kubernetes/` - K8s manifests for Airflow/MLflow

## Features

- **Auto-scaling**: Dynamic EC2 Spot instance management
- **Cost optimization**: ~60% savings vs on-demand
- **Pipeline components**: Modular, reusable stages
- **Monitoring**: MLflow experiment tracking

