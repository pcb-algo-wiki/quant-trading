"""
knowledge.extractors
====================
Phase 1 规则 NER：从文本中识别公司、产业链 segment、政策标签。

设计原则：
- 优先零依赖（不引 jieba / spaCy / LLM API），用关键词词典 + 正则。
- 输出 ``ExtractionResult``，下游 ``build_knowledge_graph.py`` 据此 upsert 节点/边。
- 预留 ``LLMEntityExtractor`` 接口（Phase 7 接入），保持调用方代码不变。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from knowledge.taxonomy import DEFAULT_TAXONOMY


# A 股 6 位代码 / 港股 5 位 / 美股 1–5 位大写字母
_SYMBOL_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?:[0-9]{6}|[0-9]{5}\.HK|[A-Z]{1,5})(?![0-9A-Za-z])"
)

# 政策相关正则（轻量；Phase 3 会扩展）
_POLICY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("five_year_plan", re.compile(r"十[四五六]五[规规划]|五年规划")),
    ("industrial_policy", re.compile(r"产业政策|产业规划|发改委")),
    ("export_control", re.compile(r"出口管制|实体清单|EAR")),
    ("anti_monopoly", re.compile(r"反垄断|垄断协议")),
    ("subsidy", re.compile(r"补贴|税收优惠|专项资金")),
]


@dataclass
class ExtractionResult:
    text: str
    companies: list[str] = field(default_factory=list)        # node_id 列表
    segments: list[str] = field(default_factory=list)         # segment node_id
    industries: list[str] = field(default_factory=list)       # industry node_id
    policy_tags: list[str] = field(default_factory=list)      # 政策标签


class EntityExtractor(Protocol):
    def extract(self, text: str) -> ExtractionResult: ...


class RuleEntityExtractor:
    """基于词典 + 正则的规则抽取器。"""

    def __init__(
        self,
        company_dict: dict[str, str] | None = None,
        taxonomy: dict | None = None,
        extra_segment_aliases: dict[str, str] | None = None,
    ) -> None:
        # company_dict: {symbol -> display_name}；同时建立 name -> symbol 反查
        self.company_by_symbol: dict[str, str] = dict(company_dict or {})
        self.company_by_name: dict[str, str] = {
            v: k for k, v in self.company_by_symbol.items() if v
        }
        self.taxonomy = taxonomy or DEFAULT_TAXONOMY
        self._segment_aliases = self._build_segment_aliases(extra_segment_aliases or {})

    # ---------- 构建 ----------

    def _build_segment_aliases(self, extra: dict[str, str]) -> dict[str, str]:
        """alias(关键词) -> segment_node_id。"""
        out: dict[str, str] = {}
        for industry, cfg in self.taxonomy.items():
            for layer in ("upstream", "midstream", "downstream"):
                for seg in cfg.get(layer, []) or []:
                    seg_id = f"{industry}:{layer}:{seg}"
                    # 默认把英文标识符当 alias；中文 alias 由 extra 覆盖
                    out[seg.lower()] = seg_id
        for alias, seg_id in extra.items():
            out[alias.lower()] = seg_id
        return out

    # ---------- 抽取 ----------

    def extract(self, text: str) -> ExtractionResult:
        if not text:
            return ExtractionResult(text="")

        companies = self._extract_companies(text)
        segments = self._extract_segments(text)
        industries = self._extract_industries(text, segments)
        policy_tags = self._extract_policy_tags(text)

        return ExtractionResult(
            text=text,
            companies=sorted(set(companies)),
            segments=sorted(set(segments)),
            industries=sorted(set(industries)),
            policy_tags=sorted(set(policy_tags)),
        )

    def _extract_companies(self, text: str) -> list[str]:
        hits: list[str] = []
        for m in _SYMBOL_PATTERN.findall(text):
            if m in self.company_by_symbol:
                hits.append(m)
        # 中文公司名命中
        for name, symbol in self.company_by_name.items():
            if name and name in text:
                hits.append(symbol)
        return hits

    def _extract_segments(self, text: str) -> list[str]:
        low = text.lower()
        hits: list[str] = []
        for alias, seg_id in self._segment_aliases.items():
            if alias and alias in low:
                hits.append(seg_id)
        return hits

    def _extract_industries(self, text: str, segment_hits: Iterable[str]) -> list[str]:
        # 行业 = 命中 segment 反推 + 行业中文/英文 key 直接命中
        out: set[str] = set()
        for seg in segment_hits:
            out.add(seg.split(":", 1)[0])
        low = text.lower()
        for industry, cfg in self.taxonomy.items():
            if industry in low:
                out.add(industry)
            name = cfg.get("name") or ""
            if name and name in text:
                out.add(industry)
        return list(out)

    def _extract_policy_tags(self, text: str) -> list[str]:
        return [tag for tag, pat in _POLICY_PATTERNS if pat.search(text)]


class LLMEntityExtractor:
    """占位实现：Phase 7 接入真实 LLM。当前回退到规则版。"""

    def __init__(self, fallback: EntityExtractor) -> None:
        self._fallback = fallback

    def extract(self, text: str) -> ExtractionResult:
        return self._fallback.extract(text)
