#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
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
import os
import re
import time
import uuid

from rag.utils.redis_conn import REDIS_CONN

CACHE_INDEX_PREFIX = "ragflow_cache_"


def _get_raw_client(conn=None):
    """Get the raw ES/OpenSearch client from a docStoreConn.

    ESConnection stores the client as `conn.es`, while OSConnection
    stores it as `conn.os`.  This helper returns whichever is available.
    """
    if conn is None:
        from common import settings
        conn = settings.docStoreConn
    if hasattr(conn, "es"):
        return conn.es
    if hasattr(conn, "os"):
        return conn.os
    raise AttributeError(
        f"{type(conn).__name__} has neither 'es' nor 'os' attribute"
    )


def _normalize_question(question: str) -> str:
    """Normalize question for consistent cache key generation.

    Strips whitespace, lowercases, and collapses multiple spaces.
    Punctuation differences (e.g. "What is RAG?" vs "What is RAG") will
    produce different keys — this is intentional for L1 exact-match.
    """
    q = question.strip().lower()
    q = re.sub(r'\s+', ' ', q)
    return q


def _cache_key(dialog_id: str, question: str) -> str:
    """Generate L1 cache key from dialog_id and normalized question."""
    normalized = _normalize_question(question)
    h = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return f"ragflow:cache:l1:{dialog_id}:{h}"


def _invalidation_set_key(dialog_id: str) -> str:
    """Key for the set of all cache keys belonging to a dialog."""
    return f"ragflow:cache:inv:{dialog_id}"


def get_l1_cache(dialog_id: str, question: str) -> dict | None:
    """Look up L1 exact-match cache. Returns cached response dict or None."""
    if not REDIS_CONN.is_alive():
        return None
    try:
        key = _cache_key(dialog_id, question)
        data = REDIS_CONN.get(key)
        if data is None:
            return None
        result = json.loads(data)
        result["cached"] = True
        logging.info("L1 cache hit for dialog=%s question='%s'", dialog_id, question[:50])
        return result
    except Exception as e:
        logging.warning("L1 cache get error: %s", e)
        return None


def set_l1_cache(dialog_id: str, question: str, response: dict, ttl: int = 86400) -> bool:
    """Store response in L1 cache with TTL. Returns True on success."""
    if not REDIS_CONN.is_alive():
        return False
    try:
        key = _cache_key(dialog_id, question)
        cache_data = {
            "answer": response.get("answer", ""),
            "reference": response.get("reference", {}),
            "prompt": response.get("prompt", ""),
            "created_at": time.time(),
        }
        success = REDIS_CONN.set(key, json.dumps(cache_data, ensure_ascii=False), ttl)
        if success:
            inv_key = _invalidation_set_key(dialog_id)
            REDIS_CONN.sadd(inv_key, key)
            # Keep invalidation set alive at least as long as the newest entry
            try:
                REDIS_CONN.REDIS.expire(inv_key, ttl)
            except Exception:
                pass
        return bool(success)
    except Exception as e:
        logging.warning("L1 cache set error: %s", e)
        return False


def invalidate_dialog_cache(dialog_id: str, tenant_id: str | None = None) -> int:
    """Delete all L1 (and optionally L2) cache entries for a dialog."""
    count = 0
    # L1 invalidation
    if REDIS_CONN.is_alive():
        try:
            inv_key = _invalidation_set_key(dialog_id)
            members = REDIS_CONN.smembers(inv_key)
            if members:
                for key in members:
                    if REDIS_CONN.delete(key):
                        count += 1
                REDIS_CONN.delete(inv_key)
                logging.info("Invalidated %d L1 cache entries for dialog=%s", count, dialog_id)
        except Exception as e:
            logging.warning("L1 cache invalidation error: %s", e)

    # L2 invalidation
    if tenant_id:
        count += invalidate_dialog_l2_cache(dialog_id, tenant_id)

    return count


def invalidate_kb_cache(kb_id: str) -> int:
    """Invalidate cache for all dialogs that reference a given KB."""
    try:
        from api.db.db_models import DB
        from api.db.services.dialog_service import DialogService

        with DB.connection_context():
            dialogs = DialogService.query(status="valid")
            count = 0
            for d in dialogs:
                if kb_id in (d.kb_ids or []):
                    count += invalidate_dialog_cache(d.id, d.tenant_id)
            return count
    except Exception as e:
        logging.warning("KB cache invalidation error: %s", e)
        return 0


# ---------------------------------------------------------------------------
# L2 Semantic Similarity Cache (ES / Infinity vector search)
# ---------------------------------------------------------------------------

def _cache_index_name(tenant_id: str) -> str:
    return f"{CACHE_INDEX_PREFIX}{tenant_id}"


def _ensure_cache_index(tenant_id: str, vector_size: int = 1024):
    """Create the cache index if it does not already exist."""
    from common import settings

    idx_name = _cache_index_name(tenant_id)
    conn = settings.docStoreConn
    if conn.index_exist(idx_name, ""):
        return

    if settings.DOC_ENGINE_INFINITY:
        # Infinity: use create_idx which reads its own mapping
        try:
            conn.create_idx(idx_name, "", vector_size)
        except Exception:
            pass
        return

    # Elasticsearch / OpenSearch: load dedicated cache mapping
    try:
        from common.file_utils import get_project_base_directory

        fp_mapping = os.path.join(
            get_project_base_directory(), "conf", "cache_es_mapping.json"
        )
        if not os.path.exists(fp_mapping):
            logging.error("Cache mapping file not found at %s", fp_mapping)
            return

        with open(fp_mapping, "r") as f:
            cache_mapping = json.load(f)

        # Adjust vector dims to match the actual embedding model
        if "properties" in cache_mapping.get("mappings", {}):
            q_vec_props = cache_mapping["mappings"]["properties"].get("q_vec", {})
            if q_vec_props:
                q_vec_props["dims"] = vector_size

        raw_client = _get_raw_client(conn)
        raw_client.indices.create(
            index=idx_name,
            body=cache_mapping,
        )
    except Exception as e:
        if "resource_already_exists_exception" in str(e).lower():
            logging.debug("Cache index already exists, skipping creation")
        else:
            logging.error("Failed to create cache index: %s", e, exc_info=True)


def get_l2_cache(
    dialog_id: str,
    question_embedding: list,
    tenant_id: str,
    similarity_threshold: float = 0.95,
) -> dict | None:
    """Look up L2 semantic cache using vector similarity search."""
    if not tenant_id:
        return None
    try:
        from common import settings
        from common.doc_store.doc_store_base import MatchDenseExpr, OrderByExpr
        from common.float_utils import get_float

        conn = settings.docStoreConn
        idx_name = _cache_index_name(tenant_id)

        if not conn.index_exist(idx_name, ""):
            return None

        embedding_data = [get_float(v) for v in question_embedding]
        vector_column_name = "q_vec"

        match_dense = MatchDenseExpr(
            vector_column_name,
            embedding_data,
            "float",
            "cosine",
            topn=1,
            extra_options={"similarity": similarity_threshold},
        )

        select_fields = [
            "dialog_id",
            "question_text",
            "answer_json",
            "reference_json",
            "prompt_text",
            "cached_at",
            "ttl",
        ]

        res = conn.search(
            select_fields=select_fields,
            highlight_fields=[],
            condition={"dialog_id": dialog_id},
            match_expressions=[match_dense],
            order_by=OrderByExpr(),
            offset=0,
            limit=1,
            index_names=idx_name,
            dataset_ids=[],
        )

        total = conn.get_total(res)
        if total == 0:
            return None

        fields = conn.get_fields(res, select_fields + ["_score"])
        if not fields:
            return None

        hit = next(iter(fields.values()))

        cached_at = float(hit.get("cached_at", 0))
        ttl = int(hit.get("ttl", 86400))
        if time.time() - cached_at > ttl:
            return None

        result = {
            "answer": hit.get("answer_json", ""),
            "reference": json.loads(hit.get("reference_json", "{}")),
            "prompt": hit.get("prompt_text", ""),
            "cached": True,
            "created_at": cached_at,
        }
        logging.info("L2 cache hit for dialog=%s", dialog_id)
        return result
    except Exception as e:
        logging.warning("L2 cache get error: %s", e)
        return None


def set_l2_cache(
    dialog_id: str,
    tenant_id: str,
    question_text: str,
    question_embedding: list,
    response: dict,
    ttl: int = 86400,
    vector_size: int = 1024,
) -> bool:
    """Store response in L2 semantic cache."""
    if not tenant_id:
        return False
    try:
        from common import settings
        from common.float_utils import get_float

        _ensure_cache_index(tenant_id, vector_size)

        conn = settings.docStoreConn
        idx_name = _cache_index_name(tenant_id)

        embedding_data = [get_float(v) for v in question_embedding]

        row = {
            "id": str(uuid.uuid4()),
            "dialog_id": dialog_id,
            "question_text": question_text,
            "answer_json": response.get("answer", ""),
            "reference_json": json.dumps(
                response.get("reference", {}), ensure_ascii=False
            ),
            "prompt_text": response.get("prompt", ""),
            "q_vec": embedding_data,
            "cached_at": time.time(),
            "ttl": ttl,
        }

        conn.insert([row], idx_name)
        logging.info(
            "L2 cache set for dialog=%s question='%s'",
            dialog_id,
            question_text[:50],
        )
        return True
    except Exception as e:
        logging.warning("L2 cache set error: %s", e)
        return False


def invalidate_dialog_l2_cache(dialog_id: str, tenant_id: str) -> int:
    """Delete all L2 cache entries for a dialog via direct ES delete_by_query."""
    try:
        from common import settings

        conn = settings.docStoreConn
        idx_name = _cache_index_name(tenant_id)

        if not conn.index_exist(idx_name, ""):
            return 0

        # Use ES delete_by_query directly to avoid the docStoreConn.delete()
        # API which injects kb_id into conditions (not applicable for cache index)
        try:
            result = _get_raw_client(conn).delete_by_query(
                index=idx_name,
                body={"query": {"term": {"dialog_id": dialog_id}}},
                refresh=True,
            )
            count = result.get("deleted", 0)
        except Exception:
            count = 0

        logging.info(
            "Invalidated L2 cache for dialog=%s count=%s", dialog_id, count
        )
        return count
    except Exception as e:
        logging.warning("L2 cache invalidation error: %s", e)
        return 0
