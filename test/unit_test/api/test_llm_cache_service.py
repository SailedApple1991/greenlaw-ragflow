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
from api.db.services.llm_cache_service import LLMExactCache
from api.db.services.llm_service import LLMBundle


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, exp=3600):
        self.values[key] = value
        self.ttls[key] = exp
        return True


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


def enabled_deepseek_config():
    return {
        "enabled": True,
        "exact_enabled": True,
        "exact_ttl_seconds": 60,
        "cache_streaming": False,
        "providers": {"DeepSeek": {"exact_enabled": True}},
    }


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
