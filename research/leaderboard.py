from __future__ import annotations


def rank_leaders(rows: list[dict]) -> list[dict]:
    ranked = []
    for row in rows:
        momentum = float(row.get("momentum", 0))
        fund_flow = float(row.get("fund_flow", 0))
        event_score = float(row.get("event_score", 0))
        score = momentum * 0.3 + fund_flow * 0.3 + event_score * 0.4
        ranked.append({**row, "score": round(score, 4)})

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked
