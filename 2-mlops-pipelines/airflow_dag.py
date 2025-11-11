"""Airflow DAG for ML pipeline orchestration."""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from datetime import datetime, timedelta
import boto3


default_args = {
    'owner': 'mlops-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}


def download_data_from_s3(**context):
    """Download training data from S3."""
    s3_hook = S3Hook(aws_conn_id='aws_default')

    bucket_name = "ml-training-data"
    key = f"datasets/train_{context['ds']}.csv"
    local_path = f"/tmp/train_data_{context['ds']}.csv"

    s3_hook.download_file(
        key=key,
        bucket_name=bucket_name,
        local_path=local_path
    )

    print(f"Downloaded data to {local_path}")
    return local_path


def preprocess_data(**context):
    """Preprocess training data."""
    ti = context['ti']
    data_path = ti.xcom_pull(task_ids='download_data')

    print(f"Preprocessing data from {data_path}")

    # Preprocessing logic would go here
    # - Data cleaning
    # - Feature engineering
    # - Train/val split

    processed_path = f"/tmp/processed_{context['ds']}.npz"
    print(f"Saved preprocessed data to {processed_path}")

    return {
        'processed_path': processed_path,
        'num_samples': 10000,
        'num_features': 128
    }


def train_model(**context):
    """Train ML model."""
    ti = context['ti']
    preprocessing_info = ti.xcom_pull(task_ids='preprocess_data')

    print(f"Training model on {preprocessing_info['num_samples']} samples")

    # Training logic would go here
    # - Load preprocessed data
    # - Initialize model
    # - Training loop
    # - Save model artifacts

    model_path = f"/tmp/model_{context['ds']}.pt"

    return {
        'model_path': model_path,
        'final_loss': 0.15,
        'epochs_trained': 50
    }


def evaluate_model(**context):
    """Evaluate trained model."""
    ti = context['ti']
    model_info = ti.xcom_pull(task_ids='train_model')

    print(f"Evaluating model: {model_info['model_path']}")

    # Evaluation logic
    metrics = {
        'accuracy': 0.94,
        'precision': 0.92,
        'recall': 0.93,
        'f1_score': 0.925,
        'auc_roc': 0.96
    }

    print(f"Evaluation metrics: {metrics}")

    # Log to MLflow
    import mlflow
    with mlflow.start_run(run_name=f"evaluation_{context['ds']}"):
        mlflow.log_metrics(metrics)

    return metrics


def upload_model_to_s3(**context):
    """Upload trained model to S3."""
    ti = context['ti']
    model_info = ti.xcom_pull(task_ids='train_model')
    metrics = ti.xcom_pull(task_ids='evaluate_model')

    # Only upload if model meets quality threshold
    if metrics['accuracy'] < 0.90:
        raise ValueError(f"Model accuracy {metrics['accuracy']} below threshold 0.90")

    s3_hook = S3Hook(aws_conn_id='aws_default')

    model_path = model_info['model_path']
    s3_key = f"models/production/model_{context['ds']}.pt"

    s3_hook.load_file(
        filename=model_path,
        key=s3_key,
        bucket_name="ml-model-artifacts",
        replace=True
    )

    print(f"Uploaded model to s3://ml-model-artifacts/{s3_key}")

    return s3_key


def trigger_deployment(**context):
    """Trigger model deployment to production."""
    ti = context['ti']
    s3_key = ti.xcom_pull(task_ids='upload_model')
    metrics = ti.xcom_pull(task_ids='evaluate_model')

    print(f"Triggering deployment for model: {s3_key}")
    print(f"Model metrics: {metrics}")

    # In production, this would:
    # - Update Kubernetes deployment
    # - Trigger canary deployment
    # - Update model registry
    # - Send notifications

    deployment_info = {
        'model_s3_path': s3_key,
        'deployment_time': context['ts'],
        'metrics': metrics,
        'status': 'deployed'
    }

    return deployment_info


# Define DAG
with DAG(
    'ml_training_pipeline',
    default_args=default_args,
    description='End-to-end ML training and deployment pipeline',
    schedule_interval='@daily',
    catchup=False,
    tags=['ml', 'training', 'production'],
) as dag:

    # Task 1: Download data
    download_task = PythonOperator(
        task_id='download_data',
        python_callable=download_data_from_s3,
        provide_context=True,
    )

    # Task 2: Preprocess data
    preprocess_task = PythonOperator(
        task_id='preprocess_data',
        python_callable=preprocess_data,
        provide_context=True,
    )

    # Task 3: Train model
    train_task = PythonOperator(
        task_id='train_model',
        python_callable=train_model,
        provide_context=True,
    )

    # Task 4: Evaluate model
    evaluate_task = PythonOperator(
        task_id='evaluate_model',
        python_callable=evaluate_model,
        provide_context=True,
    )

    # Task 5: Upload model
    upload_task = PythonOperator(
        task_id='upload_model',
        python_callable=upload_model_to_s3,
        provide_context=True,
    )

    # Task 6: Deploy model
    deploy_task = PythonOperator(
        task_id='deploy_model',
        python_callable=trigger_deployment,
        provide_context=True,
    )

    # Define task dependencies
    download_task >> preprocess_task >> train_task >> evaluate_task >> upload_task >> deploy_task
