"""财务数据防幻觉校验器

MAD（Multi-Agent Debate）的单规则替代：
- 数字一致性检查（物理不可能值）
- 来源回链强制（空 source → 低置信）
- 置信度阈值（低于 cfg.knowledge.validation.confidence_threshold 则降级）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data.filings.cninfo import FinancialRecord


@dataclass
class ValidationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 0–1


class FinancialValidator:
    """规则校验器，无需 LLM，离线可运行。

    LLM 校验路径预留：子类 override `_llm_validate` 即可接入。
    """

    def __init__(self, confidence_threshold: float = 0.6):
        self.confidence_threshold = confidence_threshold

    def validate(self, rec: "FinancialRecord") -> ValidationResult:
        """对 FinancialRecord 执行多项规则校验。

        Returns:
            ValidationResult（passed=True 表示无严重问题）
        """
        issues: list[str] = []
        confidence = 1.0

        # ── 来源回链 ─────────────────────────────────────────────────────────
        if not rec.source:
            issues.append("缺少数据来源（source 为空）")
            confidence -= 0.5
        elif rec.source not in ("cninfo", "cninfo_pdf", "edgar", "edgar_html"):
            confidence -= 0.1

        # ── 物理不可能值 ──────────────────────────────────────────────────────
        if rec.revenue is not None and rec.revenue < 0:
            issues.append(f"负营收不合理：revenue={rec.revenue}")
            confidence -= 0.5

        if rec.net_profit is not None and rec.revenue is not None and rec.revenue > 0:
            net_margin = rec.net_profit / rec.revenue
            if net_margin > 0.99:
                issues.append(f"净利率超过 99%，疑似数据错误：net_margin={net_margin:.1%}")
                confidence -= 0.3

        if rec.gross_margin is not None:
            if rec.gross_margin < 0 or rec.gross_margin > 1.0:
                issues.append(f"毛利率超出 [0,1] 范围：gross_margin={rec.gross_margin}")
                confidence -= 0.4

        if rec.rd_expense is not None and rec.rd_expense < 0:
            issues.append(f"负研发费用：rd_expense={rec.rd_expense}")
            confidence -= 0.2

        # ── 缺失关键字段 ──────────────────────────────────────────────────────
        if rec.revenue is None:
            issues.append("营收缺失，数据不完整")
            confidence -= 0.2

        confidence = max(0.0, min(1.0, confidence))
        passed = len(issues) == 0 and confidence >= self.confidence_threshold

        return ValidationResult(passed=passed, issues=issues, confidence=confidence)

    def _llm_validate(self, rec: "FinancialRecord", prompt: str) -> ValidationResult:
        """LLM 校验占位（子类实现；默认返回空通过）。"""
        return ValidationResult(passed=True, confidence=0.5)
