#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import hashlib
import json
import logging
import time
from copy import deepcopy
from typing import Any

from common.config_utils import get_base_config
from common.constants import LLMType


DEFAULT_LLM_CACHE_CONFIG = {
    "enabled": False,
    "exact_enabled": True,
    "exact_ttl_seconds": 3600,
    "cache_streaming": False,
    "providers": {
        "DeepSeek": {
            "exact_enabled": True,
        },
    },
}


class LLMExactCache:
    VERSION = "v1"
    KEY_PREFIX = f"ragflow:llm_cache:exact:{VERSION}"

    @staticmethod
    def redis_conn():
        from rag.utils.redis_conn import REDIS_CONN

        return REDIS_CONN

    @classmethod
    def config(cls) -> dict:
        conf = deepcopy(DEFAULT_LLM_CACHE_CONFIG)
        configured = deepcopy(get_base_config("llm_cache", {}) or {})
        if not isinstance(configured, dict):
            return conf

        providers = conf.pop("providers")
        configured_providers = configured.pop("providers", None)
        conf.update(configured)
        if isinstance(configured_providers, dict):
            providers.update(configured_providers)
        conf["providers"] = providers
        return conf

    @classmethod
    def is_enabled_for(
        cls,
        *,
        provider: str,
        llm_type: str,
        stream: bool = False,
        has_tools: bool = False,
        kwargs: dict | None = None,
    ) -> bool:
        conf = cls.config()
        if not conf.get("enabled", False) or not conf.get("exact_enabled", True):
            return False
        if llm_type != LLMType.CHAT.value:
            return False
        if stream and not conf.get("cache_streaming", False):
            return False
        if has_tools:
            return False
        if kwargs and kwargs.get("images"):
            return False

        provider_conf = conf.get("providers", {}).get(provider)
        if not provider_conf:
            return False
        return bool(provider_conf.get("exact_enabled", False))

    @classmethod
    def build_key(
        cls,
        *,
        tenant_id: str,
        provider: str,
        llm_name: str,
        llm_type: str,
        system: str | None,
        history: list,
        gen_conf: dict | None,
        kwargs: dict | None = None,
    ) -> str:
        payload = cls.normalize_request(
            tenant_id=tenant_id,
            provider=provider,
            llm_name=llm_name,
            llm_type=llm_type,
            system=system,
            history=history,
            gen_conf=gen_conf,
            kwargs=kwargs,
        )
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return f"{cls.KEY_PREFIX}:{digest}"

    @staticmethod
    def normalize_request(
        *,
        tenant_id: str,
        provider: str,
        llm_name: str,
        llm_type: str,
        system: str | None,
        history: list,
        gen_conf: dict | None,
        kwargs: dict | None = None,
    ) -> dict[str, Any]:
        cache_kwargs = {}
        for key, value in (kwargs or {}).items():
            if key in {"images"}:
                continue
            cache_kwargs[key] = value

        return {
            "version": LLMExactCache.VERSION,
            "tenant_id": tenant_id,
            "provider": provider,
            "llm_name": llm_name,
            "llm_type": llm_type,
            "system": system or "",
            "history": history or [],
            "gen_conf": gen_conf or {},
            "kwargs": cache_kwargs,
        }

    @classmethod
    def get(cls, key: str) -> str | None:
        try:
            raw = cls.redis_conn().get(key)
            if not raw:
                return None
            payload = json.loads(raw)
            answer = payload.get("answer")
            if not isinstance(answer, str):
                return None
            logging.info("LLM exact cache hit: %s", key)
            return answer
        except Exception:
            logging.exception("LLM exact cache read failed: %s", key)
            return None

    @classmethod
    def set(cls, key: str, answer: str, *, provider: str, llm_name: str, used_tokens: int = 0) -> None:
        if not answer:
            return

        conf = cls.config()
        ttl = int(conf.get("exact_ttl_seconds", 3600))
        if ttl <= 0:
            return

        payload = {
            "answer": answer,
            "provider": provider,
            "llm_name": llm_name,
            "used_tokens": used_tokens,
            "created_at": int(time.time()),
            "cache_type": "L0_EXACT_RESPONSE_CACHE",
            "version": cls.VERSION,
        }
        try:
            if cls.redis_conn().set(key, json.dumps(payload, ensure_ascii=False), ttl):
                logging.info("LLM exact cache write: %s", key)
        except Exception:
            logging.exception("LLM exact cache write failed: %s", key)
