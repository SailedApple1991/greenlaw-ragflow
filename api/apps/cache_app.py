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

import logging

from quart import request
from api.apps import login_required, current_user
from api.utils.api_utils import get_json_result, server_error_response
from api.db.services.cache_service import (
    CACHE_INDEX_PREFIX,
    _cache_index_name,
    _ensure_cache_index,
    _get_raw_client,
    invalidate_dialog_cache,
)
from api.db.services.dialog_service import DialogService
from api.db.services.user_service import TenantService
from rag.utils.redis_conn import REDIS_CONN
from common import settings


@manager.route("/stats", methods=["GET"])  # noqa: F821
@login_required
async def get_cache_stats():
    """Get L1/L2 cache statistics."""
    try:
        redis_alive = REDIS_CONN.is_alive()
        l1_total_keys = 0
        l1_dialog_count = 0
        if redis_alive:
            try:
                cursor = "0"
                while True:
                    cursor, keys = REDIS_CONN.REDIS.scan(cursor=cursor, match="ragflow:cache:inv:*", count=500)
                    l1_dialog_count += len(keys)
                    if int(cursor) == 0:
                        break
                cursor = "0"
                while True:
                    cursor, keys = REDIS_CONN.REDIS.scan(cursor=cursor, match="ragflow:cache:l1:*", count=500)
                    l1_total_keys += len(keys)
                    if int(cursor) == 0:
                        break
            except Exception as e:
                logging.warning("cache stats L1 error: %s", e)

        l2_total_entries = 0
        l2_indices = []
        try:
            indices_info = _get_raw_client().cat.indices(index="ragflow_cache_*", format="json")
            for idx_info in indices_info:
                docs_count = int(idx_info.get("docs.count", 0))
                l2_total_entries += docs_count
                l2_indices.append({
                    "name": idx_info.get("index", ""),
                    "docs_count": docs_count,
                    "size": idx_info.get("store.size", "0"),
                })
        except Exception as e:
            logging.warning("cache stats L2 error: %s", e)

        return get_json_result(data={
            "l1": {"total_keys": l1_total_keys, "dialog_count": l1_dialog_count, "redis_alive": redis_alive},
            "l2": {"total_entries": l2_total_entries, "indices": l2_indices},
        })
    except Exception as e:
        return server_error_response(e)


@manager.route("/tenants", methods=["GET"])  # noqa: F821
@login_required
async def list_cache_tenants():
    """List tenants that have L2 cache indices."""
    try:
        result = []
        indices_info = _get_raw_client().cat.indices(index="ragflow_cache_*", format="json")
        for idx_info in indices_info:
            index_name = idx_info.get("index", "")
            tenant_id = index_name.replace(CACHE_INDEX_PREFIX, "", 1)
            tenant_name = tenant_id
            try:
                tenants = TenantService.query(id=tenant_id)
                if tenants:
                    tenant_name = tenants[0].name
            except Exception:
                pass
            result.append({
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "index_name": index_name,
                "docs_count": int(idx_info.get("docs.count", 0)),
            })
        return get_json_result(data=result)
    except Exception as e:
        return server_error_response(e)


@manager.route("/tenants/<tenant_id>/dialogs", methods=["GET"])  # noqa: F821
@login_required
async def list_cache_dialogs(tenant_id):
    """List dialogs with cached entries for a tenant."""
    try:
        result = []
        conn = settings.docStoreConn
        idx = _cache_index_name(tenant_id)
        if not conn.index_exist(idx, ""):
            return get_json_result(data=result)

        agg_body = {
            "size": 0,
            "aggs": {"dialogs": {"terms": {"field": "dialog_id", "size": 10000}}},
        }
        res = _get_raw_client(conn).search(index=idx, body=agg_body)
        buckets = res.get("aggregations", {}).get("dialogs", {}).get("buckets", [])
        for bucket in buckets:
            dialog_id = bucket["key"]
            entry_count = bucket["doc_count"]
            dialog_name = dialog_id
            try:
                dialogs = DialogService.query(id=dialog_id)
                if dialogs:
                    dialog_name = dialogs[0].name
            except Exception:
                pass
            result.append({
                "dialog_id": dialog_id,
                "dialog_name": dialog_name,
                "entry_count": entry_count,
            })
        return get_json_result(data=result)
    except Exception as e:
        return server_error_response(e)


@manager.route("/l2/entries", methods=["GET"])  # noqa: F821
@login_required
async def list_cache_l2_entries():
    """List L2 cache entries with pagination and filtering."""
    try:
        tenant_id = request.args.get("tenant_id")
        if not tenant_id:
            return get_json_result(data={"entries": [], "total": 0, "page": 1, "page_size": 20},
                                   message="tenant_id is required", code=400)

        dialog_id = request.args.get("dialog_id")
        question_search = request.args.get("question_search")
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))

        entries = []
        total = 0
        conn = settings.docStoreConn
        idx = _cache_index_name(tenant_id)
        if not conn.index_exist(idx, ""):
            return get_json_result(data={"entries": entries, "total": total, "page": page, "page_size": page_size})

        filters = []
        if dialog_id:
            filters.append({"term": {"dialog_id": dialog_id}})
        must = []
        if question_search:
            must.append({"match": {"question_text": question_search}})

        query = {"bool": {}}
        if filters:
            query["bool"]["filter"] = filters
        if must:
            query["bool"]["must"] = must
        if not filters and not must:
            query = {"match_all": {}}

        search_body = {
            "query": query,
            "from": (page - 1) * page_size,
            "size": page_size,
            "sort": [{"cached_at": "desc"}],
            "_source": {"excludes": ["q_vec"]},
        }
        res = _get_raw_client(conn).search(index=idx, body=search_body)
        total = res.get("hits", {}).get("total", {}).get("value", 0)
        dialog_name_cache = {}
        for hit in res.get("hits", {}).get("hits", []):
            src = hit["_source"]
            d_id = src.get("dialog_id", "")
            if d_id not in dialog_name_cache:
                d_name = d_id
                try:
                    dialogs = DialogService.query(id=d_id)
                    if dialogs:
                        d_name = dialogs[0].name
                except Exception:
                    pass
                dialog_name_cache[d_id] = d_name
            entries.append({
                "id": hit["_id"],
                "dialog_id": d_id,
                "question_text": src.get("question_text", ""),
                "answer_json": src.get("answer_json", ""),
                "cached_at": src.get("cached_at"),
                "ttl": src.get("ttl"),
                "dialog_name": dialog_name_cache[d_id],
            })
        return get_json_result(data={"entries": entries, "total": total, "page": page, "page_size": page_size})
    except Exception as e:
        return server_error_response(e)


@manager.route("/l2/entries/<tenant_id>/<entry_id>", methods=["GET"])  # noqa: F821
@login_required
async def get_cache_l2_entry(tenant_id, entry_id):
    """Get a single L2 cache entry."""
    try:
        conn = settings.docStoreConn
        idx = _cache_index_name(tenant_id)
        res = _get_raw_client(conn).get(index=idx, id=entry_id, _source_excludes=["q_vec"],)
        entry = res["_source"]
        entry["id"] = res["_id"]
        return get_json_result(data=entry)
    except Exception as e:
        return server_error_response(e)


@manager.route("/l2/entries/<tenant_id>/<entry_id>", methods=["PUT"])  # noqa: F821
@login_required
async def update_cache_l2_entry(tenant_id, entry_id):
    """Update an L2 cache entry."""
    try:
        data = await request.json
        if not data:
            return get_json_result(data=False, message="Request body is required", code=400)

        conn = settings.docStoreConn
        idx = _cache_index_name(tenant_id)
        _get_raw_client(conn).update(index=idx, id=entry_id, body={"doc": data}, refresh=True)
        return get_json_result(data=True)
    except Exception as e:
        return server_error_response(e)


@manager.route("/l2/entries", methods=["POST"])  # noqa: F821
@login_required
async def create_cache_l2_entry():
    """Create a new L2 cache entry with embedding generation."""
    try:
        import time as _time
        import uuid as _uuid
        from api.db.services.llm_service import LLMBundle
        from api.db import LLMType

        data = await request.json
        if not data:
            return get_json_result(data=None, message="Request body is required", code=400)

        tenant_id = data.get("tenant_id")
        dialog_id = data.get("dialog_id")
        question_text = data.get("question_text")
        answer = data.get("answer", "")
        reference = data.get("reference", "")
        ttl = int(data.get("ttl", 86400))

        if not tenant_id or not dialog_id or not question_text:
            return get_json_result(data=None, message="tenant_id, dialog_id and question_text are required", code=400)

        mdl = LLMBundle(tenant_id, LLMType.EMBEDDING)
        _, embeddings = mdl.encode([question_text])

        vector_size = len(embeddings[0])
        _ensure_cache_index(tenant_id, vector_size)

        conn = settings.docStoreConn
        idx = _cache_index_name(tenant_id)

        doc = {
            "id": str(_uuid.uuid4()),
            "dialog_id": dialog_id,
            "question_text": question_text,
            "answer_json": answer,
            "reference_json": reference,
            "prompt_text": "",
            "q_vec": embeddings[0],
            "cached_at": _time.time(),
            "ttl": ttl,
        }
        _get_raw_client(conn).index(index=idx, body=doc, refresh=True)
        result = {k: v for k, v in doc.items() if k != "q_vec"}
        return get_json_result(data=result)
    except Exception as e:
        return server_error_response(e)


@manager.route("/l2/entries", methods=["DELETE"])  # noqa: F821
@login_required
async def delete_cache_l2_entries():
    """Batch delete L2 cache entries."""
    try:
        data = await request.json
        if not data:
            return get_json_result(data=None, message="Request body is required", code=400)

        tenant_id = data.get("tenant_id")
        entry_ids = data.get("entry_ids", [])

        if not tenant_id or not entry_ids:
            return get_json_result(data=None, message="tenant_id and entry_ids are required", code=400)

        conn = settings.docStoreConn
        idx = _cache_index_name(tenant_id)
        res = _get_raw_client(conn).delete_by_query(
            index=idx,
            body={"query": {"ids": {"values": entry_ids}}},
            refresh=True,
        )
        return get_json_result(data={"deleted": res.get("deleted", 0)})
    except Exception as e:
        return server_error_response(e)


@manager.route("/l1/dialog/<dialog_id>", methods=["DELETE"])  # noqa: F821
@login_required
async def invalidate_cache_l1_dialog(dialog_id):
    """Invalidate all L1 cache entries for a dialog."""
    try:
        count = invalidate_dialog_cache(dialog_id)
        return get_json_result(data={"count": count})
    except Exception as e:
        return server_error_response(e)
