"""ClearML pipeline for ML training and inference orchestration."""

from clearml import PipelineController
from typing import Dict, Any, List


def preprocess_data(dataset_id: str, output_path: str) -> Dict[str, Any]:
    """
    Data preprocessing step.

    Args:
        dataset_id: ClearML dataset ID
        output_path: Path to save preprocessed data

    Returns:
        Metadata about preprocessed dataset
    """
    from clearml import Dataset

    # Load dataset
    dataset = Dataset.get(dataset_id=dataset_id)
    local_path = dataset.get_local_copy()

    # Preprocessing logic (simplified)
    print(f"Preprocessing data from {local_path}")

    return {
        "processed_samples": 1000,
        "output_path": output_path,
        "dataset_version": dataset.version
    }


def train_model(
    data_path: str,
    model_config: Dict[str, Any],
    epochs: int = 10
) -> str:
    """
    Model training step.

    Args:
        data_path: Path to preprocessed data
        model_config: Model hyperparameters
        epochs: Number of training epochs

    Returns:
        Path to trained model artifact
    """
    import torch
    from clearml import Task

    task = Task.current_task()

    # Log hyperparameters
    task.connect(model_config)

    # Training loop (simplified)
    for epoch in range(epochs):
        loss = 0.5 * (1 - epoch / epochs)  # Mock decreasing loss
        task.get_logger().report_scalar(
            "training", "loss", iteration=epoch, value=loss
        )

    model_path = "/tmp/model.pt"
    print(f"Model trained and saved to {model_path}")

    return model_path


def evaluate_model(model_path: str, test_data_path: str) -> Dict[str, float]:
    """
    Model evaluation step.

    Args:
        model_path: Path to trained model
        test_data_path: Path to test dataset

    Returns:
        Evaluation metrics
    """
    from clearml import Task

    task = Task.current_task()

    # Evaluation (simplified)
    metrics = {
        "accuracy": 0.92,
        "precision": 0.89,
        "recall": 0.91,
        "f1_score": 0.90
    }

    # Log metrics
    for metric_name, metric_value in metrics.items():
        task.get_logger().report_single_value(metric_name, metric_value)

    return metrics


def deploy_model(
    model_path: str,
    deployment_target: str,
    min_accuracy: float = 0.85
) -> bool:
    """
    Model deployment step.

    Args:
        model_path: Path to trained model
        deployment_target: Deployment environment (staging/production)
        min_accuracy: Minimum accuracy threshold for deployment

    Returns:
        Deployment success status
    """
    print(f"Deploying model to {deployment_target}")
    print(f"Model path: {model_path}")

    # Deployment would happen here
    # Could involve uploading to S3, updating K8s deployment, etc.

    return True


def create_ml_pipeline(
    project_name: str = "MLOps-Pipeline",
    pipeline_name: str = "Training-Pipeline"
) -> PipelineController:
    """
    Create and configure ClearML pipeline.

    Args:
        project_name: ClearML project name
        pipeline_name: Pipeline name

    Returns:
        Configured PipelineController
    """
    pipe = PipelineController(
        project=project_name,
        name=pipeline_name,
        version="1.0.0",
        add_pipeline_tags=False
    )

    # Set default execution queue
    pipe.set_default_execution_queue("default")

    # Step 1: Data preprocessing
    pipe.add_function_step(
        name="preprocess_data",
        function=preprocess_data,
        function_kwargs={
            "dataset_id": "${pipeline.dataset_id}",
            "output_path": "/tmp/preprocessed"
        },
        function_return=["preprocessing_metadata"],
        cache_executed_step=True
    )

    # Step 2: Model training
    pipe.add_function_step(
        name="train_model",
        function=train_model,
        function_kwargs={
            "data_path": "${preprocess_data.preprocessing_metadata.output_path}",
            "model_config": {
                "learning_rate": 0.001,
                "batch_size": 32,
                "hidden_size": 256
            },
            "epochs": 50
        },
        function_return=["model_path"],
        parents=["preprocess_data"],
        cache_executed_step=False
    )

    # Step 3: Model evaluation
    pipe.add_function_step(
        name="evaluate_model",
        function=evaluate_model,
        function_kwargs={
            "model_path": "${train_model.model_path}",
            "test_data_path": "/tmp/test_data"
        },
        function_return=["metrics"],
        parents=["train_model"],
        cache_executed_step=False
    )

    # Step 4: Model deployment
    pipe.add_function_step(
        name="deploy_model",
        function=deploy_model,
        function_kwargs={
            "model_path": "${train_model.model_path}",
            "deployment_target": "staging",
            "min_accuracy": 0.85
        },
        function_return=["deployment_success"],
        parents=["evaluate_model"],
        cache_executed_step=False
    )

    return pipe


if __name__ == "__main__":
    # Create pipeline
    pipeline = create_ml_pipeline()

    # Set pipeline parameters
    pipeline.add_parameter(
        name="dataset_id",
        default="dataset-12345"
    )

    # Start pipeline remotely
    pipeline.start_remotely(queue_name="default")

    # Or run locally for testing
    # pipeline.start_locally()

    print("Pipeline started successfully!")
    print(f"Pipeline ID: {pipeline.id}")
