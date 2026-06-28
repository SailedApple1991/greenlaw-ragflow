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
import json

from common.constants import LLMType
from api.db.services import llm_cache_service
from api.db.services.llm_cache_service import LLMExactCache, LLMPromptPrefixCache, LLMSemanticCache
from api.db.services.llm_service import LLMBundle


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.sets = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, exp=3600):
        self.values[key] = value
        self.ttls[key] = exp
        return True

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)
        return True

    def smembers(self, key):
        return self.sets.get(key, set())


class FakeChatModel:
    is_tools = False

    def __init__(self):
        self.calls = 0
        self.stream_calls = 0

    def chat(self, system, history, gen_conf):
        self.calls += 1
        return "provider answer", 12

    def chat_streamly(self, system, history, gen_conf):
        self.stream_calls += 1
        yield "provider "
        yield "answer"
        yield 12


def enabled_deepseek_config(**overrides):
    config = {
        "enabled": True,
        "exact_enabled": True,
        "semantic_enabled": False,
        "prompt_prefix_enabled": False,
        "exact_ttl_seconds": 60,
        "semantic_ttl_seconds": 60,
        "semantic_similarity_threshold": 0.94,
        "cache_streaming": False,
        "eligible_task_types": [],
        "stable_context_order": False,
        "providers": {"DeepSeek": {"exact_enabled": True, "semantic_enabled": False}},
    }
    config.update(overrides)
    return config


def test_exact_cache_key_is_stable_for_equivalent_dict_order():
    first = LLMExactCache.build_key(
        tenant_id="tenant-1",
        provider="DeepSeek",
        llm_name="deepseek-chat",
        llm_type=LLMType.CHAT.value,
        system="system",
        history=[{"role": "user", "content": "hello"}],
        gen_conf={"temperature": 0, "top_p": 1},
    )
    second = LLMExactCache.build_key(
        tenant_id="tenant-1",
        provider="DeepSeek",
        llm_name="deepseek-chat",
        llm_type=LLMType.CHAT.value,
        system="system",
        history=[{"role": "user", "content": "hello"}],
        gen_conf={"top_p": 1, "temperature": 0},
    )

    assert first == second


def test_exact_cache_key_changes_by_tenant():
    base = {
        "provider": "DeepSeek",
        "llm_name": "deepseek-chat",
        "llm_type": LLMType.CHAT.value,
        "system": "system",
        "history": [{"role": "user", "content": "hello"}],
        "gen_conf": {"temperature": 0},
    }

    assert LLMExactCache.build_key(tenant_id="tenant-1", **base) != LLMExactCache.build_key(tenant_id="tenant-2", **base)


def test_exact_cache_is_enabled_only_for_configured_chat_provider(monkeypatch):
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: enabled_deepseek_config())

    assert LLMExactCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value)
    assert not LLMExactCache.is_enabled_for(provider="OpenAI", llm_type=LLMType.CHAT.value)
    assert not LLMExactCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.EMBEDDING.value)
    assert not LLMExactCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value, has_tools=True)
    assert not LLMExactCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={"images": ["image"]})


def test_exact_cache_reports_bypass_reasons(monkeypatch):
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: enabled_deepseek_config(enabled=False))

    assert LLMExactCache.bypass_reason(provider="DeepSeek", llm_type=LLMType.CHAT.value) == "disabled"

    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: enabled_deepseek_config())

    assert LLMExactCache.bypass_reason(provider="OpenAI", llm_type=LLMType.CHAT.value) == "unsupported_provider"
    assert LLMExactCache.bypass_reason(provider="DeepSeek", llm_type=LLMType.EMBEDDING.value) == "unsupported_llm_type"
    assert LLMExactCache.bypass_reason(provider="DeepSeek", llm_type=LLMType.CHAT.value, stream=True) == "streaming_disabled"
    assert LLMExactCache.bypass_reason(provider="DeepSeek", llm_type=LLMType.CHAT.value, has_tools=True) == "tool_call"


def test_exact_cache_can_be_limited_by_task_type(monkeypatch):
    config = enabled_deepseek_config(eligible_task_types=["faq", "document_qa"])
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: config)

    assert LLMExactCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={"task_type": "faq"})
    assert LLMExactCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={"llm_cache_task_type": "document_qa"})
    assert LLMExactCache.bypass_reason(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={"task_type": "agent"}) == "ineligible_task_type"
    assert LLMExactCache.bypass_reason(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={}) == "ineligible_task_type"


def test_exact_cache_read_write_roundtrip(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(LLMExactCache, "redis_conn", staticmethod(lambda: redis))
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: enabled_deepseek_config())

    key = "cache-key"
    LLMExactCache.set(key, "cached answer", provider="DeepSeek", llm_name="deepseek-chat", used_tokens=9)

    assert LLMExactCache.get(key) == "cached answer"
    assert redis.ttls[key] == 60
    payload = json.loads(redis.values[key])
    assert payload["cache_type"] == "L0_EXACT_RESPONSE_CACHE"


def test_exact_cache_miss_returns_none(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(LLMExactCache, "redis_conn", staticmethod(lambda: redis))

    assert LLMExactCache.get("missing-key") is None


def test_prompt_prefix_stable_context_order_requires_global_and_provider_config(monkeypatch):
    config = enabled_deepseek_config(
        prompt_prefix_enabled=True,
        stable_context_order=True,
        providers={"DeepSeek": {"exact_enabled": True, "prompt_prefix_enabled": True}},
    )
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: config)

    assert LLMPromptPrefixCache.is_stable_context_order_enabled("DeepSeek")
    assert not LLMPromptPrefixCache.is_stable_context_order_enabled("OpenAI")

    config["stable_context_order"] = False
    assert not LLMPromptPrefixCache.is_stable_context_order_enabled("DeepSeek")


def test_prompt_prefix_stabilizes_context_order():
    kbinfos = {
        "chunks": [
            {"doc_id": "doc-b", "position_int": [[2, 0]], "chunk_id": "chunk-2", "content_with_weight": "b"},
            {"doc_id": "doc-a", "position_int": [[3, 0]], "chunk_id": "chunk-3", "content_with_weight": "c"},
            {"doc_id": "doc-a", "position_int": [[1, 0]], "chunk_id": "chunk-1", "content_with_weight": "a"},
        ],
        "doc_aggs": [
            {"doc_id": "doc-b", "doc_name": "B"},
            {"doc_id": "doc-a", "doc_name": "A"},
        ],
    }

    stable = LLMPromptPrefixCache.stabilize_context(kbinfos)

    assert [chunk["chunk_id"] for chunk in stable["chunks"]] == ["chunk-1", "chunk-3", "chunk-2"]
    assert [doc["doc_id"] for doc in stable["doc_aggs"]] == ["doc-a", "doc-b"]
    assert [chunk["chunk_id"] for chunk in kbinfos["chunks"]] == ["chunk-2", "chunk-3", "chunk-1"]


def test_semantic_cache_requires_global_and_provider_config(monkeypatch):
    config = enabled_deepseek_config(
        semantic_enabled=True,
        eligible_task_types=["faq"],
        providers={"DeepSeek": {"exact_enabled": True, "semantic_enabled": True}},
    )
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: config)

    assert LLMSemanticCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={"task_type": "faq"})
    assert not LLMSemanticCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={"task_type": "agent"})
    assert not LLMSemanticCache.is_enabled_for(provider="OpenAI", llm_type=LLMType.CHAT.value, kwargs={"task_type": "faq"})


def test_semantic_cache_can_run_when_exact_cache_is_disabled(monkeypatch):
    config = enabled_deepseek_config(
        exact_enabled=False,
        semantic_enabled=True,
        eligible_task_types=["faq"],
        providers={"DeepSeek": {"exact_enabled": False, "semantic_enabled": True}},
    )
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: config)

    assert LLMSemanticCache.is_enabled_for(provider="DeepSeek", llm_type=LLMType.CHAT.value, kwargs={"task_type": "faq"})


def test_semantic_cache_lookup_and_write(monkeypatch):
    redis = FakeRedis()
    config = enabled_deepseek_config(
        semantic_enabled=True,
        semantic_similarity_threshold=0.9,
        providers={"DeepSeek": {"exact_enabled": True, "semantic_enabled": True}},
    )
    monkeypatch.setattr(LLMSemanticCache, "redis_conn", staticmethod(lambda: redis))
    monkeypatch.setattr(llm_cache_service, "get_base_config", lambda key, default=None: config)

    index_key = "semantic-index"
    entry_key = "semantic-entry"
    LLMSemanticCache.set(
        index_key=index_key,
        entry_key=entry_key,
        query="How do I reset my password?",
        answer="Use the reset flow.",
        embedding=[1.0, 0.0],
        provider="DeepSeek",
        llm_name="deepseek-chat",
    )

    hit = LLMSemanticCache.lookup(index_key=index_key, query_embedding=[0.99, 0.01])

    assert hit["answer"] == "Use the reset flow."
    assert hit["similarity"] >= 0.9


def test_semantic_cache_context_hash_ignores_latest_user_query():
    history_a = [{"role": "assistant", "content": "hello"}, {"role": "user", "content": "question one"}]
    history_b = [{"role": "assistant", "content": "hello"}, {"role": "user", "content": "question two"}]

    assert LLMSemanticCache.context_hash(system="system", history=history_a, gen_conf={"temperature": 0}) == LLMSemanticCache.context_hash(
        system="system", history=history_b, gen_conf={"temperature": 0}
    )


def test_llm_bundle_chat_returns_cache_hit_without_provider_call(monkeypatch):
    fake_model = FakeChatModel()
    bundle = object.__new__(LLMBundle)
    bundle.langfuse = None
    bundle.tenant_id = "tenant-1"
    bundle.llm_type = LLMType.CHAT.value
    bundle.llm_name = "deepseek-chat@DeepSeek"
    bundle.effective_llm_name = "deepseek-chat"
    bundle.llm_factory = "DeepSeek"
    bundle.is_tools = False
    bundle.verbose_tool_use = False
    bundle.mdl = fake_model

    monkeypatch.setattr(LLMExactCache, "is_enabled_for", classmethod(lambda cls, **kwargs: True))
    monkeypatch.setattr(LLMExactCache, "build_key", classmethod(lambda cls, **kwargs: "cache-key"))
    monkeypatch.setattr(LLMExactCache, "get", classmethod(lambda cls, key: "cached answer"))

    assert bundle.chat("system", [{"role": "user", "content": "hello"}], {"temperature": 0}) == "cached answer"
    assert fake_model.calls == 0


def test_llm_bundle_chat_writes_cache_after_provider_call(monkeypatch):
    fake_model = FakeChatModel()
    writes = []
    bundle = object.__new__(LLMBundle)
    bundle.langfuse = None
    bundle.tenant_id = "tenant-1"
    bundle.llm_type = LLMType.CHAT.value
    bundle.llm_name = "deepseek-chat@DeepSeek"
    bundle.effective_llm_name = "deepseek-chat"
    bundle.llm_factory = "DeepSeek"
    bundle.is_tools = False
    bundle.verbose_tool_use = False
    bundle.mdl = fake_model

    monkeypatch.setattr(LLMExactCache, "is_enabled_for", classmethod(lambda cls, **kwargs: True))
    monkeypatch.setattr(LLMExactCache, "build_key", classmethod(lambda cls, **kwargs: "cache-key"))
    monkeypatch.setattr(LLMExactCache, "get", classmethod(lambda cls, key: None))
    monkeypatch.setattr(LLMExactCache, "set", classmethod(lambda cls, *args, **kwargs: writes.append((args, kwargs))))

    assert bundle.chat("system", [{"role": "user", "content": "hello"}], {"temperature": 0}) == "provider answer"
    assert fake_model.calls == 1
    assert writes == [(("cache-key", "provider answer"), {"provider": "DeepSeek", "llm_name": "deepseek-chat", "used_tokens": 12})]


def test_llm_bundle_chat_returns_semantic_cache_hit_without_provider_call(monkeypatch):
    fake_model = FakeChatModel()
    bundle = object.__new__(LLMBundle)
    bundle.langfuse = None
    bundle.tenant_id = "tenant-1"
    bundle.llm_type = LLMType.CHAT.value
    bundle.llm_name = "deepseek-chat@DeepSeek"
    bundle.effective_llm_name = "deepseek-chat"
    bundle.llm_factory = "DeepSeek"
    bundle.is_tools = False
    bundle.verbose_tool_use = False
    bundle.mdl = fake_model

    monkeypatch.setattr(LLMExactCache, "bypass_reason", classmethod(lambda cls, **kwargs: None))
    monkeypatch.setattr(LLMExactCache, "build_key", classmethod(lambda cls, **kwargs: "exact-key"))
    monkeypatch.setattr(LLMExactCache, "get", classmethod(lambda cls, key: None))
    monkeypatch.setattr(bundle, "_semantic_cache_context", lambda *args, **kwargs: {"index_key": "semantic-index", "embedding": [1.0, 0.0]})
    monkeypatch.setattr(LLMSemanticCache, "lookup", classmethod(lambda cls, **kwargs: {"answer": "semantic answer", "similarity": 0.97}))

    assert bundle.chat("system", [{"role": "user", "content": "hello"}], {"temperature": 0}) == "semantic answer"
    assert fake_model.calls == 0


def test_llm_bundle_chat_writes_semantic_cache_after_provider_call(monkeypatch):
    fake_model = FakeChatModel()
    semantic_writes = []
    bundle = object.__new__(LLMBundle)
    bundle.langfuse = None
    bundle.tenant_id = "tenant-1"
    bundle.llm_type = LLMType.CHAT.value
    bundle.llm_name = "deepseek-chat@DeepSeek"
    bundle.effective_llm_name = "deepseek-chat"
    bundle.llm_factory = "DeepSeek"
    bundle.is_tools = False
    bundle.verbose_tool_use = False
    bundle.mdl = fake_model

    semantic_context = {"index_key": "semantic-index", "entry_key": "semantic-entry", "query": "hello", "embedding": [1.0, 0.0]}
    monkeypatch.setattr(LLMExactCache, "bypass_reason", classmethod(lambda cls, **kwargs: None))
    monkeypatch.setattr(LLMExactCache, "build_key", classmethod(lambda cls, **kwargs: "exact-key"))
    monkeypatch.setattr(LLMExactCache, "get", classmethod(lambda cls, key: None))
    monkeypatch.setattr(LLMExactCache, "set", classmethod(lambda cls, *args, **kwargs: None))
    monkeypatch.setattr(bundle, "_semantic_cache_context", lambda *args, **kwargs: semantic_context)
    monkeypatch.setattr(LLMSemanticCache, "lookup", classmethod(lambda cls, **kwargs: None))
    monkeypatch.setattr(LLMSemanticCache, "set", classmethod(lambda cls, **kwargs: semantic_writes.append(kwargs)))

    assert bundle.chat("system", [{"role": "user", "content": "hello"}], {"temperature": 0}) == "provider answer"
    assert fake_model.calls == 1
    assert semantic_writes[0]["answer"] == "provider answer"


def test_llm_bundle_chat_streamly_returns_cache_hit_without_provider_call(monkeypatch):
    fake_model = FakeChatModel()
    bundle = object.__new__(LLMBundle)
    bundle.langfuse = None
    bundle.tenant_id = "tenant-1"
    bundle.llm_type = LLMType.CHAT.value
    bundle.llm_name = "deepseek-chat@DeepSeek"
    bundle.effective_llm_name = "deepseek-chat"
    bundle.llm_factory = "DeepSeek"
    bundle.is_tools = False
    bundle.verbose_tool_use = False
    bundle.mdl = fake_model

    monkeypatch.setattr(LLMExactCache, "is_enabled_for", classmethod(lambda cls, **kwargs: True))
    monkeypatch.setattr(LLMExactCache, "build_key", classmethod(lambda cls, **kwargs: "cache-key"))
    monkeypatch.setattr(LLMExactCache, "get", classmethod(lambda cls, key: "cached answer"))

    assert list(bundle.chat_streamly("system", [{"role": "user", "content": "hello"}], {"temperature": 0})) == ["cached answer"]
    assert fake_model.stream_calls == 0


def test_llm_bundle_chat_streamly_writes_final_answer_after_provider_call(monkeypatch):
    fake_model = FakeChatModel()
    writes = []
    bundle = object.__new__(LLMBundle)
    bundle.langfuse = None
    bundle.tenant_id = "tenant-1"
    bundle.llm_type = LLMType.CHAT.value
    bundle.llm_name = "deepseek-chat@DeepSeek"
    bundle.effective_llm_name = "deepseek-chat"
    bundle.llm_factory = "DeepSeek"
    bundle.is_tools = False
    bundle.verbose_tool_use = False
    bundle.mdl = fake_model

    monkeypatch.setattr(LLMExactCache, "is_enabled_for", classmethod(lambda cls, **kwargs: True))
    monkeypatch.setattr(LLMExactCache, "build_key", classmethod(lambda cls, **kwargs: "cache-key"))
    monkeypatch.setattr(LLMExactCache, "get", classmethod(lambda cls, key: None))
    monkeypatch.setattr(LLMExactCache, "set", classmethod(lambda cls, *args, **kwargs: writes.append((args, kwargs))))
    monkeypatch.setattr("api.db.services.llm_service.TenantLLMService.increase_usage", lambda *args, **kwargs: True)

    assert list(bundle.chat_streamly("system", [{"role": "user", "content": "hello"}], {"temperature": 0})) == ["provider ", "provider answer"]
    assert fake_model.stream_calls == 1
    assert writes == [(("cache-key", "provider answer"), {"provider": "DeepSeek", "llm_name": "deepseek-chat", "used_tokens": 12})]
