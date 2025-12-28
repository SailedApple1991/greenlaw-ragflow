"""
RunPod Serverless Worker for PaddleOCR GPU Service.

This handler receives base64-encoded images and returns OCR results.
Designed to run on RunPod's serverless GPU infrastructure.
"""
import base64
import logging
import os
import time
from typing import Any, Dict, List

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runpod-ocr")

# Global OCR engine (initialized once per worker)
ocr_engine = None


def get_ocr_engine():
    """Lazy initialization of PaddleOCR engine."""
    global ocr_engine
    if ocr_engine is None:
        from paddleocr import PaddleOCR

        lang = os.environ.get("PADDLE_OCR_LANG", "en")
        logger.info(f"Initializing PaddleOCR with lang={lang}, device=gpu:0")

        ocr_engine = PaddleOCR(
            device="gpu:0",
            lang=lang,
            use_angle_cls=True,
        )
        logger.info("PaddleOCR engine initialized successfully")

    return ocr_engine


def decode_image(image_b64: str) -> np.ndarray:
    """Decode base64 image to numpy array."""
    image_bytes = base64.b64decode(image_b64)
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("Failed to decode image from base64")

    return image


def parse_paddle_result(result) -> List[Dict[str, Any]]:
    """Parse PaddleOCR 3.x result format.

    Returns list of dicts with keys: coords, text, score
    """
    boxes = []

    if not result or not isinstance(result, list) or len(result) == 0:
        return boxes

    first = result[0]

    # Check for dict-like object (PaddleOCR 3.x OCRResult)
    is_dict_like = (
        isinstance(first, dict) or
        hasattr(first, 'rec_texts') or
        (hasattr(first, '__getitem__') and hasattr(first, 'get'))
    )

    if is_dict_like:
        # New format: {'rec_texts': [...], 'rec_scores': [...], 'dt_polys': [...]}
        rec_texts = first.get('rec_texts', [])
        rec_scores = first.get('rec_scores', [])
        dt_polys = first.get('dt_polys', [])

        # Ensure lists
        if not isinstance(rec_texts, (list, tuple)):
            rec_texts = [rec_texts] if rec_texts else []
        if not isinstance(rec_scores, (list, tuple)):
            rec_scores = [rec_scores] if rec_scores else []
        if not isinstance(dt_polys, (list, tuple)):
            dt_polys = []

        for i, (text, score) in enumerate(zip(rec_texts, rec_scores)):
            if i < len(dt_polys):
                poly = dt_polys[i]

                # Convert numpy array to list
                if hasattr(poly, 'tolist'):
                    coords = poly.tolist()
                else:
                    coords = list(poly)

                # Normalize coords format to [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                coords = normalize_coords(coords)
            else:
                coords = [[0, 0], [0, 0], [0, 0], [0, 0]]

            boxes.append({
                "coords": coords,
                "text": str(text),
                "score": float(score)
            })

    return boxes


def normalize_coords(coords) -> List[List[float]]:
    """Normalize coordinate format to [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]."""
    if len(coords) == 8 and all(isinstance(x, (int, float)) for x in coords):
        # Flat format: [x1,y1,x2,y2,x3,y3,x4,y4]
        return [
            [float(coords[0]), float(coords[1])],
            [float(coords[2]), float(coords[3])],
            [float(coords[4]), float(coords[5])],
            [float(coords[6]), float(coords[7])]
        ]
    elif len(coords) == 4 and all(isinstance(x, (int, float)) for x in coords):
        # Bounding box format: [x1, y1, x2, y2]
        return [
            [float(coords[0]), float(coords[1])],
            [float(coords[2]), float(coords[1])],
            [float(coords[2]), float(coords[3])],
            [float(coords[0]), float(coords[3])]
        ]
    elif len(coords) == 4 and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in coords):
        # Already in correct format
        return [[float(p[0]), float(p[1])] for p in coords]
    else:
        return [[0, 0], [0, 0], [0, 0], [0, 0]]


def handler(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    RunPod serverless handler function.

    Input:
        job["input"]["image"]: base64-encoded image
        job["input"]["lang"]: (optional) language code, default "en"

    Output:
        {
            "boxes": [
                {"coords": [[x1,y1], ...], "text": "...", "score": 0.99},
                ...
            ],
            "elapsed_ms": 123.45
        }
    """
    start_time = time.time()

    try:
        input_data = job.get("input", {})

        # Get image from input
        image_b64 = input_data.get("image")
        if not image_b64:
            return {"error": "Missing 'image' field in input"}

        # Decode image
        logger.info("Decoding image from base64...")
        image = decode_image(image_b64)
        logger.info(f"Image decoded, shape: {image.shape}")

        # Get OCR engine
        ocr = get_ocr_engine()

        # Run OCR
        logger.info("Running OCR prediction...")
        result = ocr.predict(image)

        # Parse result
        boxes = parse_paddle_result(result)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"OCR completed: {len(boxes)} boxes in {elapsed_ms:.1f}ms")

        return {
            "boxes": boxes,
            "elapsed_ms": elapsed_ms
        }

    except Exception as e:
        logger.error(f"OCR handler error: {e}", exc_info=True)
        return {"error": str(e)}


# RunPod serverless entry point
if __name__ == "__main__":
    import runpod

    logger.info("Starting RunPod OCR serverless worker...")
    runpod.serverless.start({"handler": handler})
