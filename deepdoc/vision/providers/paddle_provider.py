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

    def _parse_result(self, result):
        """Parse PaddleOCR 3.x result format.

        PaddleOCR 3.x returns a list of dicts with 'rec_texts', 'rec_scores', 'dt_polys' keys,
        or the old format list of [box, (text, score)] tuples.
        """
        import logging
        if not result:
            return []

        try:
            # Handle PaddleOCR 3.x dict format
            if isinstance(result, list) and len(result) > 0:
                first = result[0]
                if isinstance(first, dict):
                    # New format: [{'rec_texts': [...], 'rec_scores': [...], 'dt_polys': [...]}]
                    parsed = []
                    rec_texts = first.get('rec_texts', [])
                    rec_scores = first.get('rec_scores', [])
                    dt_polys = first.get('dt_polys', [])

                    # Ensure rec_texts and rec_scores are lists
                    if not isinstance(rec_texts, (list, tuple)):
                        rec_texts = [rec_texts] if rec_texts else []
                    if not isinstance(rec_scores, (list, tuple)):
                        rec_scores = [rec_scores] if rec_scores else []

                    for i, (text, score) in enumerate(zip(rec_texts, rec_scores)):
                        # Handle different dt_polys formats
                        if i < len(dt_polys):
                            poly = dt_polys[i]
                            if hasattr(poly, 'tolist'):
                                box = poly.tolist()
                            elif isinstance(poly, (list, tuple)):
                                box = list(poly)
                            else:
                                box = [[0,0],[0,0],[0,0],[0,0]]
                        else:
                            box = [[0,0],[0,0],[0,0],[0,0]]
                        parsed.append((box, (str(text), float(score))))
                    return parsed
                elif isinstance(first, list) and len(first) > 0:
                    # Could be nested list [[box, (text, score)], ...] or old format
                    first_item = first[0]
                    if isinstance(first_item, (list, tuple)) and len(first_item) == 2:
                        second_elem = first_item[1]
                        # Check if it's [box, (text, score)] format
                        if isinstance(second_elem, (list, tuple)) and len(second_elem) == 2:
                            parsed = []
                            for item in first:
                                box, (text, score) = item
                                if hasattr(box, 'tolist'):
                                    box = box.tolist()
                                parsed.append((box, (str(text), float(score))))
                            return parsed
        except Exception as e:
            logging.warning(f"PaddleOCR result parsing error: {e}, result type: {type(result)}, result: {result[:1] if isinstance(result, list) else result}")

        return []

    def detect(self, image: np.ndarray, device_id: int | None = None):  # type: ignore[override]
        # PaddleOCR 3.x: use predict() instead of ocr(), cls is set via use_angle_cls in __init__
        result = self._engine.predict(image)
        parsed = self._parse_result(result)
        return [box for box, _ in parsed]

    def recognize(self, image: np.ndarray, box, device_id: int | None = None):  # type: ignore[override]
        """Recognize text in a cropped image region."""
        # PaddleOCR 3.x: use predict() method, detection/classification configured at init
        result = self._engine.predict(image)
        parsed = self._parse_result(result)
        if parsed:
            _, (text, score) = parsed[0]
            return text, score
        return "", 0.0

    def run(self, image: np.ndarray, device_id: int | None = None) -> OCRResult:
        # PaddleOCR 3.x: use predict() instead of ocr()
        result = self._engine.predict(image)
        parsed = self._parse_result(result)
        boxes: List[BoxWithText] = parsed
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
            parsed = self._parse_result(result)
            if parsed:
                _, (text, score) = parsed[0]
                results.append((text, score))
            else:
                results.append(("", 0.0))
        return results
