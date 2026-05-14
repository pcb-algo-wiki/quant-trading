from __future__ import annotations

from collections import defaultdict


def score_industries(events: list[dict]) -> dict[str, dict]:
    grouped = defaultdict(list)
    for e in events:
        industry = e.get("industry")
        if industry:
            grouped[industry].append(float(e.get("score", 0)))

    result = {}
    for industry, scores in grouped.items():
        total = sum(scores)
        result[industry] = {
            "score": round(total, 3),
            "event_count": len(scores),
            "avg_score": round(total / len(scores), 3) if scores else 0.0,
        }
    return result
