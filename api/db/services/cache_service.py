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

CACHE_INDEX_PREFIX = "ragflow_cache_"

# S3/MinIO bucket used for L1 cache objects
_L1_BUCKET = "ragflow_cache_l1"


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
    """Normalize question for consistent cache key generation."""
    q = question.strip().lower()
    q = re.sub(r'\s+', ' ', q)
    return q


def _cache_hash(question: str) -> str:
    """Generate SHA-256 hash from normalized question."""
    normalized = _normalize_question(question)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def _s3_path(dialog_id: str, question: str) -> str:
    """S3 object path for an L1 cache entry: {dialog_id}/{hash}.json"""
    return f"{dialog_id}/{_cache_hash(question)}.json"


def _get_storage():
    """Return the STORAGE_IMPL singleton."""
    from common import settings
    return settings.STORAGE_IMPL


def get_l1_cache(dialog_id: str, question: str) -> dict | None:
    """Look up L1 exact-match cache from S3. Returns cached response dict or None."""
    try:
        storage = _get_storage()
        data = storage.get(_L1_BUCKET, _s3_path(dialog_id, question))
        if data is None:
            return None
        result = json.loads(data)
        # Check TTL expiry
        cached_at = float(result.get("created_at", 0))
        ttl = int(result.get("ttl", 5184000))
        if time.time() - cached_at > ttl:
            return None
        result["cached"] = True
        logging.info("L1 cache hit for dialog=%s question='%s'", dialog_id, question[:50])
        return result
    except Exception as e:
        logging.warning("L1 cache get error: %s", e)
        return None


def set_l1_cache(dialog_id: str, question: str, response: dict, ttl: int = 5184000) -> bool:
    """Store response in L1 cache (S3) with TTL metadata. Returns True on success."""
    try:
        storage = _get_storage()
        cache_data = {
            "answer": response.get("answer", ""),
            "reference": response.get("reference", {}),
            "prompt": response.get("prompt", ""),
            "question_text": question,
            "created_at": time.time(),
            "ttl": ttl,
        }
        json_bytes = json.dumps(cache_data, ensure_ascii=False).encode("utf-8")
        storage.put(_L1_BUCKET, _s3_path(dialog_id, question), json_bytes)
        return True
    except Exception as e:
        logging.warning("L1 cache set error: %s", e)
        return False


def _list_s3_objects(prefix: str) -> list[str]:
    """List object keys under *prefix* inside the L1 cache bucket.

    Supports both MinIO (minio.Minio) and boto3 S3 clients.
    """
    raw = _get_storage()
    # Unwrap EncryptedStorageWrapper if present
    if hasattr(raw, "storage_impl"):
        raw = raw.storage_impl

    physical_bucket = getattr(raw, "bucket", None) or _L1_BUCKET
    prefix_path = getattr(raw, "prefix_path", None)

    if prefix_path:
        full_prefix = f"{prefix_path}/{_L1_BUCKET}/{prefix}" if raw.bucket else f"{prefix_path}/{prefix}"
        strip_prefix = f"{prefix_path}/{_L1_BUCKET}/" if raw.bucket else f"{prefix_path}/"
    elif raw.bucket:
        full_prefix = f"{_L1_BUCKET}/{prefix}"
        strip_prefix = f"{_L1_BUCKET}/"
    else:
        full_prefix = prefix
        strip_prefix = ""

    result = []
    try:
        conn = raw.conn
        if conn is None:
            return result

        # MinIO client — has list_objects
        if hasattr(conn, "list_objects"):
            for obj in conn.list_objects(physical_bucket, prefix=full_prefix, recursive=True):
                name = obj.object_name
                if strip_prefix and name.startswith(strip_prefix):
                    name = name[len(strip_prefix):]
                result.append(name)
        # boto3 S3 client — stored as conn[0]
        elif isinstance(conn, list) and len(conn) > 0:
            s3_client = conn[0]
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=physical_bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    name = obj["Key"]
                    if strip_prefix and name.startswith(strip_prefix):
                        name = name[len(strip_prefix):]
                    result.append(name)
    except Exception:
        logging.exception("Failed to list S3 objects with prefix=%s", prefix)
    return result


def invalidate_dialog_cache(dialog_id: str, tenant_id: str | None = None) -> int:
    """Delete all L1 (and optionally L2) cache entries for a dialog."""
    count = 0
    # L1 invalidation — list and delete all objects under dialog prefix
    try:
        storage = _get_storage()
        keys = _list_s3_objects(f"{dialog_id}/")
        for key in keys:
            try:
                storage.rm(_L1_BUCKET, key)
                count += 1
            except Exception:
                continue
        if count > 0:
            logging.info("Invalidated %d L1 cache entries for dialog=%s", count, dialog_id)
    except Exception as e:
        logging.warning("L1 cache invalidation error: %s", e)

    # L2 invalidation
    if tenant_id:
        count += invalidate_dialog_l2_cache(dialog_id, tenant_id)

    return count


def list_l1_entries(dialog_id: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    """List L1 cache entries with pagination. Returns {entries, total, page, page_size}."""
    try:
        storage = _get_storage()
        prefix = f"{dialog_id}/" if dialog_id else ""
        all_keys = _list_s3_objects(prefix)

        entries = []
        for key in all_keys:
            try:
                data = storage.get(_L1_BUCKET, key)
                if data is None:
                    continue
                parsed = json.loads(data)
                cached_at = float(parsed.get("created_at", 0))
                ttl = int(parsed.get("ttl", 5184000))
                ttl_remaining = max(0, int(cached_at + ttl - time.time()))
                # Parse dialog_id from key path: {dialog_id}/{hash}.json
                parts = key.split("/")
                entry_dialog_id = parts[0] if len(parts) >= 2 else ""
                entries.append({
                    "key": key,
                    "dialog_id": entry_dialog_id,
                    "question_text": parsed.get("question_text", ""),
                    "answer": parsed.get("answer", ""),
                    "cached_at": cached_at,
                    "ttl_remaining": ttl_remaining,
                })
            except Exception:
                continue

        # Sort by cached_at desc
        entries.sort(key=lambda e: e.get("cached_at", 0), reverse=True)
        total = len(entries)
        start = (page - 1) * page_size
        end = start + page_size
        return {"entries": entries[start:end], "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logging.warning("L1 cache list error: %s", e)
        return {"entries": [], "total": 0, "page": page, "page_size": page_size}


def delete_l1_entries(keys: list[str]) -> int:
    """Delete specific L1 cache entries by S3 object path. Returns count deleted."""
    try:
        storage = _get_storage()
    except Exception:
        return 0
    count = 0
    for key in keys:
        if "/" not in key or not key.endswith(".json"):
            continue
        try:
            storage.rm(_L1_BUCKET, key)
            count += 1
        except Exception:
            continue
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

        # Pick the right mapping file based on doc engine type
        is_opensearch = conn.db_type() == "opensearch"
        mapping_file = "cache_os_mapping.json" if is_opensearch else "cache_es_mapping.json"

        fp_mapping = os.path.join(
            get_project_base_directory(), "conf", mapping_file
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
                if is_opensearch:
                    q_vec_props["dimension"] = vector_size
                else:
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
        ttl = int(hit.get("ttl", 5184000))  # default 60 days
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
    ttl: int = 5184000,  # default 60 days
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
