from __future__ import annotations

import uuid
from datetime import datetime

from research.classifiers import classify_event_type


def build_events_from_news(rows: list[dict]) -> list[dict]:
    events = []
    for row in rows:
        title = str(row.get("title", "") or row.get("新闻标题", ""))
        content = str(row.get("content", "") or row.get("新闻内容", ""))
        if not title:
            continue
        classified = classify_event_type(title=title, content=content)
        sentiment = row.get("情感得分", row.get("sentiment", None))

        score = classified["score"]
        if sentiment is not None:
            try:
                score += float(sentiment) - 0.5
            except ValueError:
                pass

        events.append(
            {
                "event_id": uuid.uuid4().hex,
                "event_type": classified["event_type"],
                "industry": row.get("industry", None),
                "symbol": row.get("symbol", None),
                "title": title,
                "score": round(score, 3),
                "source": row.get("source", "unknown"),
                "published_at": row.get("time", row.get("发布时间", "")),
                "ingested_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            }
        )
    return events
