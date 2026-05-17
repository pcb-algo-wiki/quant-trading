"""Phase 16.2-16.4 — 新闻/财报/政策 LLM 富化测试"""
from __future__ import annotations

import json

import pytest

from knowledge.llm_client import MockLLM
from knowledge.news_enricher import enrich_news_item, NewsEnrichment
from knowledge.financial_extractor import extract_financial_highlights
from knowledge.policy_enricher import enrich_policy_text


def test_enrich_news_item_parses_llm_json():
    mock_resp = json.dumps({
        "summary": "AI 算力需求爆发",
        "entities": ["英伟达", "AMD"],
        "industries": ["GPU", "半导体"],
        "sentiment": 0.7,
        "impact": "利好"
    })
    llm = MockLLM(canned_response=mock_resp)
    result = enrich_news_item("英伟达 H100 销量再创新高", llm=llm)
    assert isinstance(result, NewsEnrichment)
    assert result.summary == "AI 算力需求爆发"
    assert "英伟达" in result.entities
    assert "GPU" in result.industries
    assert result.sentiment == 0.7


def test_enrich_news_item_falls_back_on_bad_json():
    llm = MockLLM(canned_response="非 JSON 文本")
    result = enrich_news_item("某新闻", llm=llm)
    # 不抛异常，返回空富化
    assert result.summary == ""
    assert result.entities == []
    assert result.sentiment == 0.0


def test_extract_financial_highlights_returns_structured_fields():
    mock_resp = json.dumps({
        "highlights": ["营收增长 30%", "毛利率提升"],
        "risks": ["美国出口管制"],
        "guidance": "Q4 收入指引上调",
        "capex_change": "+15%"
    })
    llm = MockLLM(canned_response=mock_resp)
    result = extract_financial_highlights("某公司财报全文", llm=llm)
    assert len(result.highlights) == 2
    assert len(result.risks) == 1
    assert "上调" in result.guidance


def test_enrich_policy_text_extracts_beneficiaries():
    mock_resp = json.dumps({
        "beneficiary_industries": ["新能源车", "锂电池"],
        "negative_industries": ["燃油车"],
        "strength": "high",
        "summary": "新一轮以旧换新补贴"
    })
    llm = MockLLM(canned_response=mock_resp)
    result = enrich_policy_text("汽车以旧换新补贴 ...", llm=llm)
    assert "新能源车" in result.beneficiary_industries
    assert "燃油车" in result.negative_industries
    assert result.strength == "high"
