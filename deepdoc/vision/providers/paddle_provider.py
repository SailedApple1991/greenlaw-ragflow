from __future__ import annotations

import os
from typing import List

import cv2
import numpy as np

from .base import BaseOCRProvider, BoxWithText, OCRResult

try:  # pragma: no cover - optional dependency
    from paddleocr import PaddleOCR as _PaddleEngine
except Exception:  # pragma: no cover - keep import failure silent
    _PaddleEngine = None  # type: ignore


class PaddleOCRProvider(BaseOCRProvider):
    name = "paddleocr"

    def __init__(self) -> None:
        if _PaddleEngine is None:
            raise RuntimeError("PaddleOCR is not installed. Please install paddleocr[all].")

        use_gpu = os.environ.get("PADDLE_OCR_USE_GPU", "false").lower() == "true"
        lang = os.environ.get("PADDLE_OCR_LANG", "en")
        rec_model_dir = os.environ.get("PADDLE_OCR_REC_MODEL_DIR")
        det_model_dir = os.environ.get("PADDLE_OCR_DET_MODEL_DIR")
        cls_model_dir = os.environ.get("PADDLE_OCR_CLS_MODEL_DIR")
        precision = os.environ.get("PADDLE_OCR_PRECISION")

        # PaddleOCR 3.x uses "device" instead of "use_gpu"
        device = "gpu:0" if use_gpu else "cpu"
        engine_kwargs = {
            "device": device,
            "lang": lang,
            "use_angle_cls": True,
            # Note: show_log parameter was removed in PaddleOCR 3.x
        }
        if rec_model_dir:
            engine_kwargs["rec_model_dir"] = rec_model_dir
        if det_model_dir:
            engine_kwargs["det_model_dir"] = det_model_dir
        if cls_model_dir:
            engine_kwargs["cls_model_dir"] = cls_model_dir
        if precision:
            engine_kwargs["precision"] = precision

        self._engine = _PaddleEngine(**engine_kwargs)

    @staticmethod
    def is_available() -> bool:
        return _PaddleEngine is not None

    def detect(self, image: np.ndarray, device_id: int | None = None):  # type: ignore[override]
        # PaddleOCR 3.x: use predict() instead of ocr(), cls is set via use_angle_cls in __init__
        result = self._engine.predict(image)
        boxes = []
        if result and result[0]:
            for line in result[0]:
                box, _ = line
                boxes.append(box)
        return boxes

    def recognize(self, image: np.ndarray, box, device_id: int | None = None):  # type: ignore[override]
        """Recognize text in a cropped image region."""
        # PaddleOCR 3.x: use predict() method, detection/classification configured at init
        result = self._engine.predict(image)
        if result and result[0]:
            # Extract text from first detection result
            line = result[0][0]
            _, (text, score) = line
            return text, float(score)
        return "", 0.0

    def run(self, image: np.ndarray, device_id: int | None = None) -> OCRResult:
        # PaddleOCR 3.x: use predict() instead of ocr()
        result = self._engine.predict(image)
        boxes: List[BoxWithText] = []
        if result and result[0]:
            for line in result[0]:
                box, (text, score) = line
                boxes.append((box, (text, float(score))))
        return OCRResult(boxes=boxes, elapsed_det=0.0, elapsed_rec=0.0)

    # Additional methods required by pdf_parser.py for full compatibility
    def get_rotate_crop_image(self, img, points):
        """Crop and rotate image region defined by quadrilateral points."""
        assert len(points) == 4, "shape of points must be 4*2"
        points = np.array(points, dtype=np.float32)
        img_crop_width = int(
            max(
                np.linalg.norm(points[0] - points[1]),
                np.linalg.norm(points[2] - points[3])))
        img_crop_height = int(
            max(
                np.linalg.norm(points[0] - points[3]),
                np.linalg.norm(points[1] - points[2])))
        pts_std = np.float32([[0, 0], [img_crop_width, 0],
                              [img_crop_width, img_crop_height],
                              [0, img_crop_height]])
        M = cv2.getPerspectiveTransform(points, pts_std)
        dst_img = cv2.warpPerspective(
            img,
            M, (img_crop_width, img_crop_height),
            borderMode=cv2.BORDER_REPLICATE,
            flags=cv2.INTER_CUBIC)
        return dst_img

    def recognize_batch(self, img_list, device_id: int | None = None):
        """Batch recognize text from a list of cropped images."""
        results = []
        for img in img_list:
            # PaddleOCR 3.x: use predict() method
            result = self._engine.predict(img)
            if result and result[0]:
                line = result[0][0]
                _, (text, score) = line
                results.append((text, float(score)))
            else:
                results.append(("", 0.0))
        return results
