from __future__ import annotations


POSITIVE_HINTS = ["利好", "支持", "增长", "突破", "超预期", "订单大增", "景气"]
NEGATIVE_HINTS = ["利空", "下滑", "风险", "不及预期", "减产", "亏损", "收缩"]
POLICY_HINTS = ["政策", "工信部", "发改委", "财政部", "国务院", "监管"]
EARNINGS_HINTS = ["财报", "营收", "净利润", "毛利率", "业绩", "指引"]


def classify_event_type(title: str, content: str = "") -> dict:
    text = f"{title} {content}"
    score = 0.0

    if any(k in text for k in POSITIVE_HINTS):
        score += 1.0
    if any(k in text for k in NEGATIVE_HINTS):
        score -= 1.0

    if any(k in text for k in POLICY_HINTS):
        event_type = "policy_positive" if score >= 0 else "policy_negative"
    elif any(k in text for k in EARNINGS_HINTS):
        event_type = "earnings_positive" if score >= 0 else "earnings_negative"
    else:
        event_type = "industry_update"

    return {"event_type": event_type, "score": score}
