"""Phase 16.2 — 新闻 LLM 富化"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from knowledge.llm_client import BaseLLM


NEWS_PROMPT_TEMPLATE = """你是金融新闻分析助手。读完新闻后输出严格 JSON：
{{
  "summary": "<= 50 字摘要",
  "entities": ["相关公司或人物列表"],
  "industries": ["所属行业列表"],
  "sentiment": -1~1 数值,
  "impact": "利好/利空/中性"
}}

新闻：
{text}
"""


@dataclass
class NewsEnrichment:
    summary: str = ""
    entities: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    sentiment: float = 0.0
    impact: str = ""


def enrich_news_item(text: str, llm: BaseLLM) -> NewsEnrichment:
    """调用 LLM 富化新闻；解析失败时返回空对象。"""
    prompt = NEWS_PROMPT_TEMPLATE.format(text=text)
    try:
        raw = llm.complete(prompt)
        data = json.loads(raw)
        return NewsEnrichment(
            summary=str(data.get("summary", ""))[:200],
            entities=list(data.get("entities", []) or []),
            industries=list(data.get("industries", []) or []),
            sentiment=float(data.get("sentiment", 0.0) or 0.0),
            impact=str(data.get("impact", "")),
        )
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return NewsEnrichment()
