"""Phase 16.3 — 财报关键信息提取"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from knowledge.llm_client import BaseLLM


FINREP_PROMPT_TEMPLATE = """你是财报阅读助手。请基于文本输出 JSON：
{{
  "highlights": ["管理层亮点 3-5 条"],
  "risks": ["风险点 2-4 条"],
  "guidance": "<= 80 字业绩指引摘要",
  "capex_change": "资本开支变化方向（如 +15% / 持平 / -10%）"
}}

财报全文：
{text}
"""


@dataclass
class FinancialHighlights:
    highlights: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    guidance: str = ""
    capex_change: str = ""


def extract_financial_highlights(text: str, llm: BaseLLM) -> FinancialHighlights:
    prompt = FINREP_PROMPT_TEMPLATE.format(text=text)
    try:
        raw = llm.complete(prompt)
        data = json.loads(raw)
        return FinancialHighlights(
            highlights=list(data.get("highlights", []) or []),
            risks=list(data.get("risks", []) or []),
            guidance=str(data.get("guidance", "")),
            capex_change=str(data.get("capex_change", "")),
        )
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return FinancialHighlights()
