"""ROLES 框架提示模板 + 规则版护城河打分

ROLES = Role / Objective / Limits / Expectations / Safeguards

score_moat() 不依赖 LLM，可在离线环境运行。
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from data.filings.cninfo import FinancialRecord

# ── ROLES 模板 ──────────────────────────────────────────────────────────────

_ROLES_TEMPLATE = """\
Role: {role}
Objective: {objective}
Limits: {limits}
Expectations: {expectations}
Safeguards: {safeguards}
"""


def build_roles_prompt(
    role: str,
    objective: str,
    limits: str,
    expectations: str,
    safeguards: str,
) -> str:
    """构建 ROLES 框架提示词。"""
    return _ROLES_TEMPLATE.format(
        role=role,
        objective=objective,
        limits=limits,
        expectations=expectations,
        safeguards=safeguards,
    )


# ── 预设角色 ──────────────────────────────────────────────────────────────────

FINANCIAL_ANALYST_PROMPT = build_roles_prompt(
    role="资深财报分析师，专注 A 股上市公司基本面研究",
    objective="核实财务数据的内部一致性，识别潜在会计风险",
    limits="只参考公开披露文件；不做买卖建议；不猜测未披露信息",
    expectations="以 JSON 格式输出：{passed: bool, issues: [str], confidence: float}",
    safeguards="数字出入超 5% 需标注存疑；缺失数据不得推断；盈利预测不得超 3 年",
)

EDGAR_ANALYST_PROMPT = build_roles_prompt(
    role="SEC 文件分析师，专注美股 10-K 风险因素与财务数据",
    objective="提取三大表关键科目并标注数据来源页码",
    limits="只读取提供的 10-K 文本；不引用第三方数据",
    expectations="以 JSON 输出 {revenue, net_income, total_assets, risk_factors: [str]}",
    safeguards="所有数字必须带单位（millions USD）；缺失字段标注 null 不得填 0",
)

# ── 规则版护城河打分 ─────────────────────────────────────────────────────────

def score_moat(
    rec: "FinancialRecord",
    policy_alignment: float = 0.0,
) -> dict:
    """规则版护城河打分，无需 LLM，离线可运行。

    五个维度，各 0-1 分，total_score = 加权平均 × 5（上限 5.0）。

    Args:
        rec: FinancialRecord
        policy_alignment: 政策契合度 0-1（由 research.policy_alignment 提供，默认 0）

    Returns:
        {total_score, dimensions: {brand, switching_cost, cost_advantage, rd_moat, policy}}
    """
    scores: dict[str, float] = {}

    # 毛利率 > 40% → 品牌或成本优势
    gm = rec.gross_margin or 0.0
    scores["brand"] = min(1.0, max(0.0, (gm - 0.20) / 0.40))

    # 净利率代理切换成本（高净利率 → 高定价权）
    net_margin = 0.0
    if rec.revenue and rec.net_profit and rec.revenue > 0:
        net_margin = rec.net_profit / rec.revenue
    scores["switching_cost"] = min(1.0, max(0.0, net_margin / 0.25))

    # 毛利率 - 净利率之差：差越小代表费用控制好（成本优势）
    if gm > 0 and net_margin > 0:
        spread = gm - net_margin
        scores["cost_advantage"] = min(1.0, max(0.0, 1.0 - spread / 0.5))
    else:
        scores["cost_advantage"] = 0.0

    # 研发费用 / 收入 > 5% → 技术护城河
    rd_ratio = 0.0
    if rec.revenue and rec.rd_expense and rec.revenue > 0:
        rd_ratio = rec.rd_expense / rec.revenue
    scores["rd_moat"] = min(1.0, max(0.0, rd_ratio / 0.10))

    # 政策契合度直接映射
    scores["policy"] = min(1.0, max(0.0, float(policy_alignment)))

    weights = {
        "brand": 0.30,
        "switching_cost": 0.25,
        "cost_advantage": 0.20,
        "rd_moat": 0.15,
        "policy": 0.10,
    }
    weighted = sum(scores[k] * weights[k] for k in scores)
    total = round(weighted * 5.0, 2)

    return {"total_score": total, "dimensions": scores}
