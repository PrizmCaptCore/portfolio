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
