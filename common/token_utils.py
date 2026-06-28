#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
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


import os
import tiktoken

from common.file_utils import get_project_base_directory

tiktoken_cache_dir = get_project_base_directory()
os.environ["TIKTOKEN_CACHE_DIR"] = tiktoken_cache_dir
# encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
encoder = tiktoken.get_encoding("cl100k_base")


def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    try:
        code_list = encoder.encode(string)
        return len(code_list)
    except Exception:
        return 0

def total_token_count_from_response(resp):
    """
    Extract token count from LLM response in various formats.

    Handles None responses and different response structures from various LLM providers.
    Returns 0 if token count cannot be determined.
    """
    if resp is None:
        return 0

    if hasattr(resp, "usage") and hasattr(resp.usage, "total_tokens"):
        try:
            return resp.usage.total_tokens
        except Exception:
            pass

    if hasattr(resp, "usage_metadata") and hasattr(resp.usage_metadata, "total_tokens"):
        try:
            return resp.usage_metadata.total_tokens
        except Exception:
            pass

    if isinstance(resp, dict) and 'usage' in resp and 'total_tokens' in resp['usage']:
        try:
            return resp["usage"]["total_tokens"]
        except Exception:
            pass

    if isinstance(resp, dict) and 'usage' in resp and 'input_tokens' in resp['usage'] and 'output_tokens' in resp['usage']:
        try:
            return resp["usage"]["input_tokens"] + resp["usage"]["output_tokens"]
        except Exception:
            pass

    if isinstance(resp, dict) and 'meta' in resp and 'tokens' in resp['meta'] and 'input_tokens' in resp['meta']['tokens'] and 'output_tokens' in resp['meta']['tokens']:
        try:
            return resp["meta"]["tokens"]["input_tokens"] + resp["meta"]["tokens"]["output_tokens"]
        except Exception:
            pass
    return 0


def provider_cache_token_details_from_response(resp) -> dict:
    """
    Extract provider prompt-cache token counters from common response shapes.

    Providers expose these fields inconsistently. This keeps the extraction
    defensive and returns only counters that are present and non-zero.
    """
    if resp is None:
        return {}

    usage = _get_response_value(resp, "usage")
    usage_metadata = _get_response_value(resp, "usage_metadata")
    candidates = [
        usage,
        usage_metadata,
        _get_response_value(usage, "prompt_tokens_details"),
        _get_response_value(usage, "input_token_details"),
        _get_response_value(usage_metadata, "input_token_details"),
        _get_response_value(usage_metadata, "cache_tokens_details"),
    ]

    field_aliases = {
        "cache_read_input_tokens": [
            "cache_read_input_tokens",
            "cacheReadInputTokens",
            "cache_read_tokens",
            "cache_read",
            "cached_tokens",
        ],
        "cache_write_input_tokens": [
            "cache_write_input_tokens",
            "cacheWriteInputTokens",
            "cache_creation_input_tokens",
            "cache_creation_tokens",
            "cache_creation",
            "cache_write",
        ],
    }

    details = {}
    for out_key, aliases in field_aliases.items():
        value = 0
        for candidate in candidates:
            for alias in aliases:
                value = _get_response_value(candidate, alias, 0)
                if value:
                    break
            if value:
                break
        try:
            value = int(value)
        except Exception:
            value = 0
        if value:
            details[out_key] = value

    return details


def _get_response_value(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return getattr(obj, key)
    except Exception:
        return default


def truncate(string: str, max_len: int) -> str:
    """Returns truncated text if the length of text exceed max_len."""
    return encoder.decode(encoder.encode(string)[:max_len])
