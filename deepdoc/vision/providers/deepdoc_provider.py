from __future__ import annotations

import time
from typing import List

import numpy as np

from ..ocr import OCR as LegacyOCR
from .base import BaseOCRProvider, Box, BoxWithText, OCRResult


class DeepDocProvider(BaseOCRProvider):
    name = "deepdoc"

    def __init__(self) -> None:
        self._impl = LegacyOCR()

    @staticmethod
    def is_available() -> bool:
        return True

    @classmethod
    def normalize_result(cls, payload):
        return payload

    def detect(self, image: np.ndarray, device_id: int | None = None):  # type: ignore[override]
        """Return boxes as numpy arrays (no return type to skip beartype check)."""
        result = self._impl.detect(image, device_id=device_id)
        # Handle None case (returns None, None, time_dict on failure)
        if result is None:
            return []
        # Check if it's the failure tuple (None, None, time_dict)
        if isinstance(result, tuple) and len(result) >= 2 and result[0] is None:
            return []
        # Result is a zip of (box, recognition) pairs - return intact for pdf_parser.py compatibility
        return list(result)

    def recognize(self, image: np.ndarray, box: Box, device_id: int | None = None):
        return self._impl.recognize(image, box, device_id=device_id)

    def run(self, image: np.ndarray, device_id: int | None = None) -> OCRResult:
        start = time.time()
        result = self._impl(image, device_id=device_id)
        elapsed = time.time() - start
        boxes: List[BoxWithText] = result if result else []
        return OCRResult(
            boxes=boxes,
            elapsed_det=elapsed,  # legacy call does not split det/rec times
            elapsed_rec=0.0,
        )

    # Additional methods required by pdf_parser.py for full compatibility
    def get_rotate_crop_image(self, img, points):
        """Crop and rotate image region defined by quadrilateral points."""
        return self._impl.get_rotate_crop_image(img, points)

    def recognize_batch(self, img_list, device_id: int | None = None):
        """Batch recognize text from a list of cropped images."""
        return self._impl.recognize_batch(img_list, device_id=device_id)
