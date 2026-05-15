from __future__ import annotations

import re


def parse_financial_metrics(text: str) -> dict:
    """
    从财报文本中提取关键指标（MVP 规则提取）。
    """
    metric_patterns = {
        "revenue_yoy": r"营收[同比]*([+-]?\d+\.?\d*)%",
        "net_profit_yoy": r"净利润[同比]*([+-]?\d+\.?\d*)%",
        "gross_margin": r"毛利率([+-]?\d+\.?\d*)%",
        "rd_ratio": r"研发[投入费用]*([+-]?\d+\.?\d*)%",
    }

    result = {}
    for key, pattern in metric_patterns.items():
        m = re.search(pattern, text)
        if m:
            result[key] = float(m.group(1))
    return result
