"""RunPod Serverless OCR Provider for RAGFlow.

This provider sends images to RunPod's serverless GPU infrastructure
for OCR processing using PaddleOCR.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import List, Optional

import cv2
import numpy as np
import requests

from .base import BaseOCRProvider, BoxWithText, OCRResult

logger = logging.getLogger("runpod_provider")


class RunPodOCRProvider(BaseOCRProvider):
    """OCR provider that uses RunPod Serverless GPU for PaddleOCR inference."""

    name = "runpod"

    def __init__(self) -> None:
        self.api_key = os.environ.get("RUNPOD_API_KEY", "")
        self.endpoint_id = os.environ.get("RUNPOD_OCR_ENDPOINT_ID", "")
        self.timeout = int(os.environ.get("RUNPOD_OCR_TIMEOUT", "120"))
        self.max_retries = int(os.environ.get("RUNPOD_OCR_MAX_RETRIES", "3"))
        self.fallback_provider_name = os.environ.get("RUNPOD_OCR_FALLBACK", "deepdoc")

        if not self.api_key or not self.endpoint_id:
            logger.warning(
                "RunPod OCR provider not configured. "
                "Set RUNPOD_API_KEY and RUNPOD_OCR_ENDPOINT_ID environment variables."
            )

        self._fallback_provider: Optional[BaseOCRProvider] = None
        self._init_fallback_provider()

    def _init_fallback_provider(self) -> None:
        """Initialize fallback provider for when RunPod is unavailable."""
        if not self.fallback_provider_name:
            return

        try:
            if self.fallback_provider_name == "deepdoc":
                from .deepdoc_provider import DeepDocProvider
                self._fallback_provider = DeepDocProvider()
                logger.info("Fallback provider initialized: DeepDoc")
            elif self.fallback_provider_name == "paddleocr":
                from .paddle_provider import PaddleOCRProvider
                if PaddleOCRProvider.is_available():
                    self._fallback_provider = PaddleOCRProvider()
                    logger.info("Fallback provider initialized: PaddleOCR (local)")
        except Exception as e:
            logger.warning(f"Failed to initialize fallback provider: {e}")

    @staticmethod
    def is_available() -> bool:
        """Check if RunPod provider is configured."""
        api_key = os.environ.get("RUNPOD_API_KEY", "")
        endpoint_id = os.environ.get("RUNPOD_OCR_ENDPOINT_ID", "")
        return bool(api_key and endpoint_id)

    def _encode_image(self, image: np.ndarray) -> str:
        """Encode numpy image to base64 JPEG string."""
        # Encode as JPEG for smaller payload
        _, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return base64.b64encode(buffer).decode('utf-8')

    def _call_runpod_api(self, image: np.ndarray) -> dict:
        """Call RunPod serverless API with the image.

        Args:
            image: numpy array of the image

        Returns:
            API response dict with 'boxes' key

        Raises:
            Exception: If API call fails after all retries
        """
        if not self.api_key or not self.endpoint_id:
            raise RuntimeError(
                "RunPod OCR not configured. "
                "Set RUNPOD_API_KEY and RUNPOD_OCR_ENDPOINT_ID."
            )

        url = f"https://api.runpod.ai/v2/{self.endpoint_id}/runsync"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Encode image to base64
        image_b64 = self._encode_image(image)

        payload = {
            "input": {
                "image": image_b64
            }
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"RunPod API call attempt {attempt + 1}/{self.max_retries}")

                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    result = response.json()

                    # Check for error in response
                    if "error" in result.get("output", {}):
                        raise RuntimeError(f"RunPod worker error: {result['output']['error']}")

                    return result.get("output", {})

                elif response.status_code == 401:
                    raise RuntimeError("Invalid RunPod API key")

                elif response.status_code == 404:
                    raise RuntimeError(f"RunPod endpoint not found: {self.endpoint_id}")

                else:
                    last_error = f"RunPod API error: HTTP {response.status_code} - {response.text}"
                    logger.warning(last_error)

            except requests.exceptions.Timeout:
                last_error = f"RunPod API timeout after {self.timeout}s"
                logger.warning(last_error)

            except requests.exceptions.RequestException as e:
                last_error = f"RunPod API request failed: {e}"
                logger.warning(last_error)

            # Exponential backoff before retry
            if attempt < self.max_retries - 1:
                sleep_time = 2 ** attempt
                logger.info(f"Retrying in {sleep_time}s...")
                time.sleep(sleep_time)

        raise RuntimeError(f"RunPod API failed after {self.max_retries} attempts: {last_error}")

    def _parse_api_response(self, response: dict) -> List[BoxWithText]:
        """Parse RunPod API response into BoxWithText format.

        Args:
            response: dict with 'boxes' key containing list of
                      {"coords": [[x,y],...], "text": str, "score": float}

        Returns:
            List of (box, (text, score)) tuples
        """
        boxes = response.get("boxes", [])
        result = []

        for box in boxes:
            coords = box.get("coords", [[0, 0]] * 4)
            text = box.get("text", "")
            score = box.get("score", 0.0)

            # Convert coords to tuple format expected by RAGFlow
            box_coords = tuple(tuple(pt) for pt in coords)
            result.append((box_coords, (text, score)))

        return result

    def detect(self, image: np.ndarray, device_id: int | None = None) -> List[BoxWithText]:
        """Detect and recognize text in image using RunPod GPU.

        Args:
            image: numpy array of the image (BGR format)
            device_id: ignored, RunPod handles GPU assignment

        Returns:
            List of (box, (text, score)) tuples
        """
        try:
            response = self._call_runpod_api(image)
            return self._parse_api_response(response)

        except Exception as e:
            logger.error(f"RunPod OCR failed: {e}")

            # Try fallback provider
            if self._fallback_provider:
                logger.info(f"Falling back to {self.fallback_provider_name} provider")
                return self._fallback_provider.detect(image, device_id)

            raise

    def recognize(self, image: np.ndarray, box, device_id: int | None = None):
        """Recognize text in a cropped image region.

        For RunPod, we run full detection on the cropped region.
        """
        result = self.detect(image, device_id)
        if result:
            _, (text, score) = result[0]
            return text, score
        return "", 0.0

    def run(self, image: np.ndarray, device_id: int | None = None) -> OCRResult:
        """Full OCR pipeline.

        Args:
            image: numpy array of the image
            device_id: ignored

        Returns:
            OCRResult with boxes and timing info
        """
        start_time = time.time()

        try:
            response = self._call_runpod_api(image)
            boxes = self._parse_api_response(response)
            elapsed = response.get("elapsed_ms", 0) / 1000.0

            return OCRResult(
                boxes=boxes,
                elapsed_det=elapsed,
                elapsed_rec=0.0
            )

        except Exception as e:
            logger.error(f"RunPod OCR failed: {e}")

            if self._fallback_provider:
                logger.info(f"Falling back to {self.fallback_provider_name} provider")
                return self._fallback_provider.run(image, device_id)

            raise

    # Additional methods for pdf_parser.py compatibility
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
        """Batch recognize text from a list of cropped images.

        For RunPod, we process images one by one (could be optimized
        to batch in a single API call in the future).
        """
        if not img_list:
            return []

        results = []
        drop_score = 0.5

        for img in img_list:
            try:
                boxes = self.detect(img, device_id)
                if boxes:
                    _, (text, score) = boxes[0]
                    if float(score) < drop_score:
                        text = ''
                    results.append(str(text))
                else:
                    results.append("")
            except Exception as e:
                logger.warning(f"recognize_batch failed for image: {e}")
                results.append("")

        return results
