"""Phase 16 — LLM 客户端与缓存测试"""
from __future__ import annotations

import pytest

from knowledge.llm_client import (
    BaseLLM,
    MockLLM,
    LLMCache,
    get_llm_client,
    LLMConfig,
)


def test_mock_llm_returns_canned_response():
    llm = MockLLM(canned_response='{"summary": "测试"}')
    resp = llm.complete("提示")
    assert resp == '{"summary": "测试"}'
    assert llm.call_count == 1


def test_mock_llm_supports_response_map():
    llm = MockLLM(response_map={"keyword_a": "ans_a", "keyword_b": "ans_b"})
    assert llm.complete("含 keyword_a 的提示") == "ans_a"
    assert llm.complete("含 keyword_b 的提示") == "ans_b"


def test_llm_cache_round_trip(tmp_path):
    cache = LLMCache(str(tmp_path / "cache.db"))
    cache.set("prompt1", "model_x", "response1")
    hit = cache.get("prompt1", "model_x")
    assert hit == "response1"


def test_llm_cache_returns_none_for_missing(tmp_path):
    cache = LLMCache(str(tmp_path / "cache.db"))
    assert cache.get("nope", "model_x") is None


def test_llm_cache_separates_by_model(tmp_path):
    cache = LLMCache(str(tmp_path / "cache.db"))
    cache.set("p", "m1", "r1")
    cache.set("p", "m2", "r2")
    assert cache.get("p", "m1") == "r1"
    assert cache.get("p", "m2") == "r2"


def test_get_llm_client_with_mock_backend():
    cfg = LLMConfig(backend="mock", api_key="", model="mock-1")
    llm = get_llm_client(cfg)
    assert isinstance(llm, MockLLM)


def test_get_llm_client_disabled_returns_none():
    cfg = LLMConfig(backend="disabled", api_key="", model="")
    llm = get_llm_client(cfg)
    assert llm is None


def test_base_llm_is_abstract():
    with pytest.raises(TypeError):
        BaseLLM()
