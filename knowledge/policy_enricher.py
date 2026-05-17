"""Phase 16.4 — 政策 LLM 富化"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from knowledge.llm_client import BaseLLM


POLICY_PROMPT_TEMPLATE = """你是政策分析助手。输出严格 JSON：
{{
  "beneficiary_industries": ["受益行业链"],
  "negative_industries": ["受损行业链"],
  "strength": "high/medium/low",
  "summary": "<= 60 字政策要点"
}}

政策文本：
{text}
"""


@dataclass
class PolicyEnrichment:
    beneficiary_industries: list[str] = field(default_factory=list)
    negative_industries: list[str] = field(default_factory=list)
    strength: str = "low"
    summary: str = ""


def enrich_policy_text(text: str, llm: BaseLLM) -> PolicyEnrichment:
    prompt = POLICY_PROMPT_TEMPLATE.format(text=text)
    try:
        raw = llm.complete(prompt)
        data = json.loads(raw)
        return PolicyEnrichment(
            beneficiary_industries=list(data.get("beneficiary_industries", []) or []),
            negative_industries=list(data.get("negative_industries", []) or []),
            strength=str(data.get("strength", "low")),
            summary=str(data.get("summary", "")),
        )
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return PolicyEnrichment()
