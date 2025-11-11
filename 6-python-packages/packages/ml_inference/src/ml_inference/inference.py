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
