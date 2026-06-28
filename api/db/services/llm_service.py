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
import inspect
import logging
import re
from common.token_utils import num_tokens_from_string
from functools import partial
from typing import Generator
from common.constants import LLMType
from api.db.db_models import LLM
from api.db.services.llm_cache_service import LLMExactCache, LLMSemanticCache
from api.db.services.common_service import CommonService
from api.db.services.tenant_llm_service import LLM4Tenant, TenantLLMService


class LLMService(CommonService):
    model = LLM


def get_init_tenant_llm(user_id):
    from common import settings
    tenant_llm = []

    model_configs = {
        LLMType.CHAT: settings.CHAT_CFG,
        LLMType.EMBEDDING: settings.EMBEDDING_CFG,
        LLMType.SPEECH2TEXT: settings.ASR_CFG,
        LLMType.IMAGE2TEXT: settings.IMAGE2TEXT_CFG,
        LLMType.RERANK: settings.RERANK_CFG,
    }

    seen = set()
    factory_configs = []
    for factory_config in [
        settings.CHAT_CFG,
        settings.EMBEDDING_CFG,
        settings.ASR_CFG,
        settings.IMAGE2TEXT_CFG,
        settings.RERANK_CFG,
    ]:
        factory_name = factory_config["factory"]
        if factory_name not in seen:
            seen.add(factory_name)
            factory_configs.append(factory_config)

    for factory_config in factory_configs:
        for llm in LLMService.query(fid=factory_config["factory"]):
            tenant_llm.append(
                {
                    "tenant_id": user_id,
                    "llm_factory": factory_config["factory"],
                    "llm_name": llm.llm_name,
                    "model_type": llm.model_type,
                    "api_key": model_configs.get(llm.model_type, {}).get("api_key", factory_config["api_key"]),
                    "api_base": model_configs.get(llm.model_type, {}).get("base_url", factory_config["base_url"]),
                    "max_tokens": llm.max_tokens if llm.max_tokens else 8192,
                }
            )

    unique = {}
    for item in tenant_llm:
        key = (item["tenant_id"], item["llm_factory"], item["llm_name"])
        if key not in unique:
            unique[key] = item
    return list(unique.values())


class LLMBundle(LLM4Tenant):
    CACHE_INTERNAL_KWARGS = {
        "llm_cache_task_type",
        "llm_cache_permission_scope_hash",
        "llm_cache_retrieved_context_hash",
        "llm_cache_document_hash",
        "llm_cache_output_format_version",
    }

    def __init__(self, tenant_id, llm_type, llm_name=None, lang="Chinese", **kwargs):
        super().__init__(tenant_id, llm_type, llm_name, lang, **kwargs)
        model_config = TenantLLMService.get_model_config(tenant_id, llm_type, llm_name)
        self.llm_factory = model_config.get("llm_factory", "")
        self.effective_llm_name = model_config.get("llm_name", llm_name)

    def bind_tools(self, toolcall_session, tools):
        if not self.is_tools:
            logging.warning(f"Model {self.llm_name} does not support tool call, but you have assigned one or more tools to it!")
            return
        self.mdl.bind_tools(toolcall_session, tools)

    def encode(self, texts: list):
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="encode", model=self.llm_name, input={"texts": texts})

        safe_texts = []
        for text in texts:
            token_size = num_tokens_from_string(text)
            if token_size > self.max_length:
                target_len = int(self.max_length * 0.95)
                safe_texts.append(text[:target_len])
            else:
                safe_texts.append(text)

        embeddings, used_tokens = self.mdl.encode(safe_texts)

        llm_name = getattr(self, "llm_name", None)
        if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, used_tokens, llm_name):
            logging.error("LLMBundle.encode can't update token usage for {}/EMBEDDING used_tokens: {}".format(self.tenant_id, used_tokens))

        if self.langfuse:
            generation.update(usage_details={"total_tokens": used_tokens})
            generation.end()

        return embeddings, used_tokens

    def encode_queries(self, query: str):
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="encode_queries", model=self.llm_name, input={"query": query})

        emd, used_tokens = self.mdl.encode_queries(query)
        llm_name = getattr(self, "llm_name", None)
        if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, used_tokens, llm_name):
            logging.error("LLMBundle.encode_queries can't update token usage for {}/EMBEDDING used_tokens: {}".format(self.tenant_id, used_tokens))

        if self.langfuse:
            generation.update(usage_details={"total_tokens": used_tokens})
            generation.end()

        return emd, used_tokens

    def similarity(self, query: str, texts: list):
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="similarity", model=self.llm_name, input={"query": query, "texts": texts})

        sim, used_tokens = self.mdl.similarity(query, texts)
        if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, used_tokens):
            logging.error("LLMBundle.similarity can't update token usage for {}/RERANK used_tokens: {}".format(self.tenant_id, used_tokens))

        if self.langfuse:
            generation.update(usage_details={"total_tokens": used_tokens})
            generation.end()

        return sim, used_tokens

    def describe(self, image, max_tokens=300):
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="describe", metadata={"model": self.llm_name})

        txt, used_tokens = self.mdl.describe(image)
        if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, used_tokens):
            logging.error("LLMBundle.describe can't update token usage for {}/IMAGE2TEXT used_tokens: {}".format(self.tenant_id, used_tokens))

        if self.langfuse:
            generation.update(output={"output": txt}, usage_details={"total_tokens": used_tokens})
            generation.end()

        return txt

    def describe_with_prompt(self, image, prompt):
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="describe_with_prompt", metadata={"model": self.llm_name, "prompt": prompt})

        txt, used_tokens = self.mdl.describe_with_prompt(image, prompt)
        if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, used_tokens):
            logging.error("LLMBundle.describe can't update token usage for {}/IMAGE2TEXT used_tokens: {}".format(self.tenant_id, used_tokens))

        if self.langfuse:
            generation.update(output={"output": txt}, usage_details={"total_tokens": used_tokens})
            generation.end()

        return txt

    def transcription(self, audio):
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="transcription", metadata={"model": self.llm_name})

        txt, used_tokens = self.mdl.transcription(audio)
        if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, used_tokens):
            logging.error("LLMBundle.transcription can't update token usage for {}/SEQUENCE2TXT used_tokens: {}".format(self.tenant_id, used_tokens))

        if self.langfuse:
            generation.update(output={"output": txt}, usage_details={"total_tokens": used_tokens})
            generation.end()

        return txt

    def tts(self, text: str) -> Generator[bytes, None, None]:
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="tts", input={"text": text})

        for chunk in self.mdl.tts(text):
            if isinstance(chunk, int):
                if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, chunk, self.llm_name):
                    logging.error("LLMBundle.tts can't update token usage for {}/TTS".format(self.tenant_id))
                return
            yield chunk

        if self.langfuse:
            generation.end()

    def _remove_reasoning_content(self, txt: str) -> str:
        first_think_start = txt.find("<think>")
        if first_think_start == -1:
            return txt

        last_think_end = txt.rfind("</think>")
        if last_think_end == -1:
            return txt

        if last_think_end < first_think_start:
            return txt

        return txt[last_think_end + len("</think>") :]

    @staticmethod
    def _clean_param(chat_partial, **kwargs):
        func = chat_partial.func
        sig = inspect.signature(func)
        support_var_args = False
        allowed_params = set()

        for param in sig.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                support_var_args = True
            elif param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
                allowed_params.add(param.name)
        if support_var_args:
            return kwargs
        else:
            return {k: v for k, v in kwargs.items() if k in allowed_params}

    @staticmethod
    def _provider_kwargs(kwargs: dict) -> dict:
        return {k: v for k, v in (kwargs or {}).items() if k not in LLMBundle.CACHE_INTERNAL_KWARGS}

    def chat(self, system: str, history: list, gen_conf: dict = {}, **kwargs) -> str:
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="chat", model=self.llm_name, input={"system": system, "history": history})

        chat_partial = partial(self.mdl.chat, system, history, gen_conf)
        if self.is_tools and self.mdl.is_tools:
            chat_partial = partial(self.mdl.chat_with_tools, system, history, gen_conf)

        use_kwargs = self._clean_param(chat_partial, **kwargs)
        provider_kwargs = self._provider_kwargs(use_kwargs)
        cache_key = None
        semantic_cache = None
        has_tools = bool(self.is_tools and self.mdl.is_tools)
        cache_bypass_reason = LLMExactCache.bypass_reason(provider=self.llm_factory, llm_type=self.llm_type, has_tools=has_tools, kwargs=use_kwargs)
        if cache_bypass_reason is None:
            cache_key = LLMExactCache.build_key(
                tenant_id=self.tenant_id,
                provider=self.llm_factory,
                llm_name=self.effective_llm_name,
                llm_type=self.llm_type,
                system=system,
                history=history,
                gen_conf=gen_conf,
                kwargs=use_kwargs,
            )
            cached = LLMExactCache.get(cache_key)
            if cached is not None:
                if self.langfuse:
                    generation.update(output={"output": cached}, metadata={"llm_cache": "L0_EXACT_RESPONSE_CACHE"})
                    generation.end()
                return cached
        else:
            logging.debug("LLM exact cache bypass: %s", cache_bypass_reason)

        semantic_cache = self._semantic_cache_context(system, history, gen_conf, use_kwargs, has_tools)
        if semantic_cache:
            cached = LLMSemanticCache.lookup(index_key=semantic_cache["index_key"], query_embedding=semantic_cache["embedding"])
            if cached and cached.get("requires_validation") and not self._validate_semantic_cache_hit(semantic_cache["query"], cached.get("query", ""), gen_conf):
                cached = None
            if cached:
                answer = cached["answer"]
                if self.langfuse:
                    generation.update(output={"output": answer}, metadata={"llm_cache": "L1_SEMANTIC_RESPONSE_CACHE", "similarity": cached.get("similarity")})
                    generation.end()
                return answer

        txt, used_tokens = chat_partial(**provider_kwargs)
        txt = self._remove_reasoning_content(txt)

        if not self.verbose_tool_use:
            txt = re.sub(r"<tool_call>.*?</tool_call>", "", txt, flags=re.DOTALL)

        if cache_key and isinstance(txt, str):
            LLMExactCache.set(cache_key, txt, provider=self.llm_factory, llm_name=self.effective_llm_name, used_tokens=used_tokens)
        if semantic_cache and isinstance(txt, str):
            LLMSemanticCache.set(
                index_key=semantic_cache["index_key"],
                entry_key=semantic_cache["entry_key"],
                query=semantic_cache["query"],
                answer=txt,
                embedding=semantic_cache["embedding"],
                provider=self.llm_factory,
                llm_name=self.effective_llm_name,
            )

        if isinstance(txt, int) and not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, used_tokens, self.llm_name):
            logging.error("LLMBundle.chat can't update token usage for {}/CHAT llm_name: {}, used_tokens: {}".format(self.tenant_id, self.llm_name, used_tokens))

        if self.langfuse:
            generation.update(output={"output": txt}, usage_details={"total_tokens": used_tokens})
            generation.end()

        return txt

    def _semantic_cache_context(self, system: str, history: list, gen_conf: dict, kwargs: dict, has_tools: bool) -> dict | None:
        if not LLMSemanticCache.is_enabled_for(provider=self.llm_factory, llm_type=self.llm_type, has_tools=has_tools, kwargs=kwargs):
            return None

        query = LLMSemanticCache.query_text(history)
        if not query:
            return None

        try:
            embedding_mdl = LLMBundle(self.tenant_id, LLMType.EMBEDDING)
            embedding, _ = embedding_mdl.encode_queries(query)
            embedding = LLMSemanticCache.embedding_to_list(embedding)
            context_hash = LLMSemanticCache.context_hash(system=system, history=history, gen_conf=gen_conf, kwargs=kwargs)
            task_type = LLMExactCache._task_type(kwargs)
            index_key = LLMSemanticCache.index_key(
                tenant_id=self.tenant_id,
                provider=self.llm_factory,
                llm_name=self.effective_llm_name,
                task_type=task_type,
                context_hash=context_hash,
            )
            return {
                "query": query,
                "embedding": embedding,
                "index_key": index_key,
                "entry_key": LLMSemanticCache.entry_key(index_key, query),
            }
        except Exception:
            logging.exception("LLM semantic cache context build failed")
            return None

    def _validate_semantic_cache_hit(self, query: str, cached_query: str, gen_conf: dict) -> bool:
        if not query or not cached_query:
            return False
        validator_system = (
            "Decide whether two user questions are semantically equivalent for reusing the same answer. "
            "Return only YES or NO."
        )
        validator_history = [
            {
                "role": "user",
                "content": f"Question A:\n{cached_query}\n\nQuestion B:\n{query}",
            }
        ]
        validator_conf = {"temperature": 0, "max_completion_tokens": 4}
        if isinstance(gen_conf, dict) and "stop" in gen_conf:
            validator_conf["stop"] = gen_conf["stop"]
        try:
            answer, _ = self.mdl.chat(validator_system, validator_history, validator_conf)
            passed = str(answer).strip().upper().startswith("YES")
            logging.info("LLM semantic cache validation %s", "passed" if passed else "failed")
            return passed
        except Exception:
            logging.exception("LLM semantic cache validation failed")
            return False

    def chat_streamly(self, system: str, history: list, gen_conf: dict = {}, **kwargs):
        if self.langfuse:
            generation = self.langfuse.start_generation(trace_context=self.trace_context, name="chat_streamly", model=self.llm_name, input={"system": system, "history": history})

        ans = ""
        chat_partial = partial(self.mdl.chat_streamly, system, history, gen_conf)
        total_tokens = 0
        if self.is_tools and self.mdl.is_tools:
            chat_partial = partial(self.mdl.chat_streamly_with_tools, system, history, gen_conf)
        use_kwargs = self._clean_param(chat_partial, **kwargs)
        provider_kwargs = self._provider_kwargs(use_kwargs)
        cache_key = None
        has_tools = bool(self.is_tools and self.mdl.is_tools)
        cache_bypass_reason = LLMExactCache.bypass_reason(provider=self.llm_factory, llm_type=self.llm_type, stream=True, has_tools=has_tools, kwargs=use_kwargs)
        if cache_bypass_reason is None:
            cache_key = LLMExactCache.build_key(
                tenant_id=self.tenant_id,
                provider=self.llm_factory,
                llm_name=self.effective_llm_name,
                llm_type=self.llm_type,
                system=system,
                history=history,
                gen_conf=gen_conf,
                kwargs=use_kwargs,
            )
            cached = LLMExactCache.get(cache_key)
            if cached is not None:
                if self.langfuse:
                    generation.update(output={"output": cached}, metadata={"llm_cache": "L0_EXACT_RESPONSE_CACHE"})
                    generation.end()
                yield cached
                return
        else:
            logging.debug("LLM exact cache bypass: %s", cache_bypass_reason)

        for txt in chat_partial(**provider_kwargs):
            if isinstance(txt, int):
                total_tokens = txt
                if self.langfuse:
                    generation.update(output={"output": ans})
                    generation.end()
                break

            if txt.endswith("</think>"):
                ans = ans[: -len("</think>")]

            if not self.verbose_tool_use:
                txt = re.sub(r"<tool_call>.*?</tool_call>", "", txt, flags=re.DOTALL)

            ans += txt
            yield ans

        if cache_key and ans:
            LLMExactCache.set(cache_key, ans, provider=self.llm_factory, llm_name=self.effective_llm_name, used_tokens=total_tokens)

        if total_tokens > 0:
            if not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, txt, self.llm_name):
                logging.error("LLMBundle.chat_streamly can't update token usage for {}/CHAT llm_name: {}, content: {}".format(self.tenant_id, self.llm_name, txt))
