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
    "semantic_enabled": False,
    "prompt_prefix_enabled": False,
    "exact_ttl_seconds": 3600,
    "semantic_ttl_seconds": 3600,
    "semantic_similarity_threshold": 0.94,
    "cache_streaming": False,
    "eligible_task_types": [],
    "stable_context_order": False,
    "providers": {
        "DeepSeek": {
            "exact_enabled": True,
            "semantic_enabled": False,
            "prompt_prefix_enabled": True,
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
        return cls.bypass_reason(provider=provider, llm_type=llm_type, stream=stream, has_tools=has_tools, kwargs=kwargs) is None

    @classmethod
    def bypass_reason(
        cls,
        *,
        provider: str,
        llm_type: str,
        stream: bool = False,
        has_tools: bool = False,
        kwargs: dict | None = None,
    ) -> str | None:
        conf = cls.config()
        if not conf.get("enabled", False) or not conf.get("exact_enabled", True):
            return "disabled"
        if llm_type != LLMType.CHAT.value:
            return "unsupported_llm_type"
        if stream and not conf.get("cache_streaming", False):
            return "streaming_disabled"
        if has_tools:
            return "tool_call"
        if kwargs and kwargs.get("images"):
            return "image_input"

        task_type = cls._task_type(kwargs)
        eligible_task_types = conf.get("eligible_task_types") or []
        if eligible_task_types and task_type not in set(str(x).strip() for x in eligible_task_types if str(x).strip()):
            return "ineligible_task_type"

        provider_conf = conf.get("providers", {}).get(provider)
        if not provider_conf:
            return "unsupported_provider"
        if not provider_conf.get("exact_enabled", False):
            return "provider_disabled"
        return None

    @staticmethod
    def _task_type(kwargs: dict | None) -> str:
        if not kwargs:
            return ""
        return str(kwargs.get("task_type") or kwargs.get("llm_cache_task_type") or "").strip()

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
                logging.info("LLM exact cache miss: %s", key)
                return None
            payload = json.loads(raw)
            answer = payload.get("answer")
            if not isinstance(answer, str):
                logging.info("LLM exact cache miss: invalid payload for %s", key)
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


class LLMPromptPrefixCache:
    @classmethod
    def is_stable_context_order_enabled(cls, provider: str) -> bool:
        conf = LLMExactCache.config()
        if not conf.get("enabled", False) or not conf.get("prompt_prefix_enabled", False):
            return False
        if not conf.get("stable_context_order", False):
            return False

        provider_conf = conf.get("providers", {}).get(provider)
        if not provider_conf:
            return False
        return bool(provider_conf.get("prompt_prefix_enabled", False))

    @classmethod
    def stabilize_context(cls, kbinfos: dict) -> dict:
        if not kbinfos:
            return kbinfos

        stable = deepcopy(kbinfos)
        stable["chunks"] = sorted(stable.get("chunks", []), key=cls._chunk_sort_key)
        stable["doc_aggs"] = sorted(stable.get("doc_aggs", []), key=cls._doc_agg_sort_key)
        return stable

    @staticmethod
    def _chunk_sort_key(chunk: dict) -> tuple:
        return (
            str(chunk.get("doc_id") or chunk.get("document_id") or ""),
            LLMPromptPrefixCache._positions_sort_key(chunk.get("positions") or chunk.get("position_int")),
            str(chunk.get("chunk_id") or chunk.get("id") or ""),
            str(chunk.get("content_with_weight") or chunk.get("content") or "")[:128],
        )

    @staticmethod
    def _doc_agg_sort_key(doc_agg: dict) -> tuple:
        return (
            str(doc_agg.get("doc_id") or ""),
            str(doc_agg.get("doc_name") or ""),
        )

    @staticmethod
    def _positions_sort_key(positions: Any) -> str:
        if positions is None:
            return ""
        try:
            return json.dumps(positions, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            return str(positions)


class LLMSemanticCache:
    VERSION = "v1"
    INDEX_PREFIX = f"ragflow:llm_cache:semantic:index:{VERSION}"
    ENTRY_PREFIX = f"ragflow:llm_cache:semantic:entry:{VERSION}"

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
        conf = LLMExactCache.config()
        if not conf.get("enabled", False) or not conf.get("semantic_enabled", False):
            return False
        if llm_type != LLMType.CHAT.value:
            return False
        if stream:
            return False
        if has_tools:
            return False
        if kwargs and kwargs.get("images"):
            return False

        task_type = LLMExactCache._task_type(kwargs)
        eligible_task_types = conf.get("eligible_task_types") or []
        if eligible_task_types and task_type not in set(str(x).strip() for x in eligible_task_types if str(x).strip()):
            return False

        provider_conf = conf.get("providers", {}).get(provider)
        if not provider_conf:
            return False
        return bool(provider_conf.get("semantic_enabled", False))

    @classmethod
    def query_text(cls, history: list) -> str:
        for message in reversed(history or []):
            if message.get("role") == "user":
                return str(message.get("content") or "").strip()
        return ""

    @classmethod
    def context_hash(cls, *, system: str | None, history: list, gen_conf: dict | None, kwargs: dict | None = None) -> str:
        prior_history = list(history or [])
        if prior_history and prior_history[-1].get("role") == "user":
            prior_history = prior_history[:-1]
        payload = {
            "system": system or "",
            "history": prior_history,
            "gen_conf": gen_conf or {},
            "permission_scope_hash": cls.cache_metadata_value(kwargs, "permission_scope_hash"),
            "retrieved_context_hash": cls.cache_metadata_value(kwargs, "retrieved_context_hash"),
            "document_hash": cls.cache_metadata_value(kwargs, "document_hash"),
            "output_format_version": cls.cache_metadata_value(kwargs, "output_format_version"),
        }
        return cls.stable_hash(payload)

    @classmethod
    def cache_metadata_value(cls, kwargs: dict | None, name: str) -> str:
        if not kwargs:
            return ""
        return str(kwargs.get(name) or kwargs.get(f"llm_cache_{name}") or "").strip()

    @classmethod
    def stable_hash(cls, payload: Any) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()

    @classmethod
    def retrieved_context_hash(cls, kbinfos: dict | None) -> str:
        chunks = []
        for chunk in (kbinfos or {}).get("chunks", []) or []:
            chunks.append(
                {
                    "chunk_id": chunk.get("chunk_id") or chunk.get("id") or "",
                    "doc_id": chunk.get("doc_id") or "",
                    "content": chunk.get("content") or chunk.get("content_ltks") or chunk.get("content_with_weight") or "",
                }
            )
        return cls.stable_hash(chunks)

    @classmethod
    def document_hash(cls, kbinfos: dict | None) -> str:
        docs = []
        for doc in (kbinfos or {}).get("doc_aggs", []) or []:
            docs.append({"doc_id": doc.get("doc_id") or "", "count": doc.get("count", 0)})
        return cls.stable_hash(sorted(docs, key=lambda doc: (doc["doc_id"], doc["count"])))

    @classmethod
    def permission_scope_hash(cls, *, tenant_id: str, kb_ids: list | None = None, doc_ids: list | None = None) -> str:
        return cls.stable_hash(
            {
                "tenant_id": tenant_id,
                "kb_ids": sorted(str(kb_id) for kb_id in (kb_ids or []) if kb_id),
                "doc_ids": sorted(str(doc_id) for doc_id in (doc_ids or []) if doc_id),
            }
        )

    @classmethod
    def index_key(cls, *, tenant_id: str, provider: str, llm_name: str, task_type: str, context_hash: str) -> str:
        raw = json.dumps(
            {
                "tenant_id": tenant_id,
                "provider": provider,
                "llm_name": llm_name,
                "task_type": task_type,
                "context_hash": context_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"{cls.INDEX_PREFIX}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    @classmethod
    def entry_key(cls, index_key: str, query: str) -> str:
        return f"{cls.ENTRY_PREFIX}:{hashlib.sha256((index_key + query).encode('utf-8')).hexdigest()}"

    @classmethod
    def lookup(cls, *, index_key: str, query_embedding: list[float]) -> dict | None:
        conf = LLMExactCache.config()
        threshold = float(conf.get("semantic_similarity_threshold", 0.94))
        best = None
        best_score = 0.0

        try:
            entry_keys = cls.redis_conn().smembers(index_key) or []
            for entry_key in entry_keys:
                raw = cls.redis_conn().get(entry_key)
                if not raw:
                    continue
                entry = json.loads(raw)
                score = cls.cosine_similarity(query_embedding, entry.get("embedding") or [])
                if score > best_score:
                    best = entry
                    best_score = score
            if best and best_score >= threshold:
                logging.info("LLM semantic cache hit: %s score=%.4f", index_key, best_score)
                best["similarity"] = best_score
                return best
            logging.info("LLM semantic cache miss: %s best_score=%.4f", index_key, best_score)
        except Exception:
            logging.exception("LLM semantic cache lookup failed: %s", index_key)
        return None

    @classmethod
    def set(cls, *, index_key: str, entry_key: str, query: str, answer: str, embedding: list[float], provider: str, llm_name: str) -> None:
        if not query or not answer or not embedding:
            return

        conf = LLMExactCache.config()
        ttl = int(conf.get("semantic_ttl_seconds", 3600))
        if ttl <= 0:
            return

        payload = {
            "query": query,
            "answer": answer,
            "embedding": cls.embedding_to_list(embedding),
            "provider": provider,
            "llm_name": llm_name,
            "created_at": int(time.time()),
            "cache_type": "L1_SEMANTIC_RESPONSE_CACHE",
            "version": cls.VERSION,
        }
        try:
            redis = cls.redis_conn()
            redis.set(entry_key, json.dumps(payload, ensure_ascii=False), ttl)
            redis.sadd(index_key, entry_key)
            redis.set(f"{index_key}:ttl", "1", ttl)
            logging.info("LLM semantic cache write: %s", index_key)
        except Exception:
            logging.exception("LLM semantic cache write failed: %s", index_key)

    @staticmethod
    def redis_conn():
        return LLMExactCache.redis_conn()

    @staticmethod
    def embedding_to_list(embedding) -> list[float]:
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        return [float(x) for x in embedding]

    @classmethod
    def cosine_similarity(cls, left, right) -> float:
        left = cls.embedding_to_list(left)
        right = cls.embedding_to_list(right)
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sum(a * a for a in left) ** 0.5
        right_norm = sum(b * b for b in right) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)
