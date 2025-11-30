"""OCR provider registry for DeepDoc."""
from __future__ import annotations

import os
from functools import lru_cache

from .base import BaseOCRProvider, OCRResult
from .deepdoc_provider import DeepDocProvider
from .paddle_provider import PaddleOCRProvider

_DEFAULT_PROVIDER = os.environ.get("OCR_PROVIDER", "deepdoc")
# Use plain dict without type annotation to avoid beartype runtime checks
_AVAILABLE_PROVIDERS = {
    "deepdoc": DeepDocProvider,
    "paddleocr": PaddleOCRProvider,
}


def register_provider(name: str, cls) -> None:
    _AVAILABLE_PROVIDERS[name] = cls


def list_providers():
    return {name: cls.is_available() for name, cls in _AVAILABLE_PROVIDERS.items()}


def set_default_provider(name: str) -> None:
    global _DEFAULT_PROVIDER
    if name not in _AVAILABLE_PROVIDERS:
        raise ValueError(f"Unknown OCR provider: {name}")
    _DEFAULT_PROVIDER = name
    get_provider.cache_clear()  # type: ignore[attr-defined]


@lru_cache(maxsize=8)
def get_provider(name: str | None = None) -> BaseOCRProvider:
    provider_name = name or _DEFAULT_PROVIDER
    cls = _AVAILABLE_PROVIDERS.get(provider_name)
    if cls is None:
        raise ValueError(f"Unknown OCR provider: {provider_name}")
    instance = cls()
    return instance


def run_ocr(image, *, provider: str | None = None) -> OCRResult:
    return get_provider(provider).run(image)
