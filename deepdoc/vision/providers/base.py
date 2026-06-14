"""Provider interfaces for OCR engines."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import numpy as np

Box = Sequence[Sequence[float]]
Recognition = Tuple[str, float]
BoxWithText = Tuple[Box, Recognition]


@dataclass(slots=True)
class OCRResult:
    boxes: List[BoxWithText]
    elapsed_det: float
    elapsed_rec: float


class BaseOCRProvider(ABC):
    """Common contract every OCR implementation must satisfy."""

    name: str = ""

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        """Return True if this provider can be used."""
        ...

    @abstractmethod
    def detect(self, image: np.ndarray, device_id: int | None = None) -> List[Box]:
        """Return quadrilateral boxes for text regions in image coordinates."""
        ...

    @abstractmethod
    def recognize(self, image: np.ndarray, box: Box, device_id: int | None = None) -> Recognition:
        """Recognize text within a cropped region defined by ``box``."""
        ...

    @abstractmethod
    def run(self, image: np.ndarray, device_id: int | None = None) -> OCRResult:
        """Full detection + recognition pipeline for convenience."""
        ...


def normalize_box(raw_box: Iterable[Iterable[float]]) -> List[List[float]]:
    """Convert provider-specific box representation into a 4x2 list."""
    pts = [list(pt) for pt in raw_box]
    if len(pts) != 4:
        raise ValueError("OCR boxes must contain four points")
    return pts
