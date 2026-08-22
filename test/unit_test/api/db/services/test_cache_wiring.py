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

"""Guard the semantic cache wiring against silent removal.

The L1/L2 cache lives in api/db/services/cache_service.py, but it only does
anything if the chat path calls into it. That wiring has been dropped twice by
upstream commits replayed on top of the fork -- both times the cache admin API
and UI kept working, so nothing looked broken while every chat request bypassed
the cache entirely.

These tests parse the source instead of importing it: importing dialog_service
pulls in settings, the doc store and the database, which a unit test cannot
stand up. Source-level assertions are enough for the failure mode we care about
-- the call sites disappearing.
"""

import ast
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[5] / "api" / "db" / "services"


def _function_source(path: Path, func_name: str) -> str:
    """Return the source of a top-level (async) function, nested defs included."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.unparse(node)
    raise AssertionError(f"{func_name} not found in {path.name}")


@pytest.mark.p2
def test_l2_cache_is_wired_into_async_chat():
    src = _function_source(SERVICES / "dialog_service.py", "async_chat")
    assert "get_l2_cache" in src, "L2 cache lookup missing from async_chat -- chat will never hit the cache"
    assert "set_l2_cache" in src, "L2 cache write missing from async_chat -- chat will never populate the cache"


@pytest.mark.p2
def test_l1_cache_is_wired_into_async_completion():
    src = _function_source(SERVICES / "conversation_service.py", "async_completion")
    assert "get_l1_cache" in src, "L1 cache lookup missing from async_completion"
    assert "set_l1_cache" in src, "L1 cache write missing from async_completion"


@pytest.mark.p2
def test_l2_lookup_runs_before_retrieval():
    """The L2 lookup only pays off if it short-circuits the expensive work."""
    src = _function_source(SERVICES / "dialog_service.py", "async_chat")
    assert src.index("get_l2_cache") < src.index("settings.retriever"), (
        "L2 lookup must precede retrieval, otherwise a cache hit still pays for retrieval"
    )


@pytest.mark.p2
def test_cache_failures_do_not_break_chat():
    """Every cache call site must sit inside a try/except."""
    path = SERVICES / "dialog_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
            for name in ("get_l2_cache", "set_l2_cache"):
                if f"{name}(" in body:
                    guarded.add(name)
    assert guarded == {"get_l2_cache", "set_l2_cache"}, (
        f"cache calls not wrapped in try/except: {{'get_l2_cache', 'set_l2_cache'}} - {guarded}"
    )
