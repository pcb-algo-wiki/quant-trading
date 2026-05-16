#!/usr/bin/env python3
"""
数据填充脚本 - 将新闻/事件/知识写入SQLite
"""
from __future__ import annotations

import sys, json, uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.realtime_news import get_realtime_news, sentiment_score
from data_store.db import get_connection
from research.classifiers import classify_event_type


def fill_news_and_events() -> dict:
    """抓取新闻，打分，写入 news_items + industry_events"""
    news_df = get_realtime_news()
    rows = news_df.to_dict("records") if not news_df.empty else []

    news_count = 0
    event_count = 0

    with get_connection() as conn:
        now = datetime.utcnow().replace(microsecond=0).isoformat()

        for row in rows:
            title = str(row.get("title", "") or "")
            if not title:
                continue

            # 情感打分
            sent = sentiment_score(title)

            # 写入 news_items
            content = str(row.get("content", "") or "")
            if content in ("", "nan", "None"):
                content = ""
            url = str(row.get("url", "") or "")
            published = str(row.get("time", "") or now)
            content_hash = hash((title, published, url, content))

            conn.execute(
                """INSERT OR IGNORE INTO news_items
                (source, title, published_at, url, content, content_hash, sentiment, related_symbol, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(row.get("source", "unknown")),
                    title,
                    published,
                    url,
                    content,
                    str(content_hash),
                    round(sent, 3),
                    row.get("related_symbol"),
                    now,
                ),
            )
            news_count += 1

            # 写入 industry_events
            classified = classify_event_type(title=title, content=content)
            score = classified["score"] + sent - 0.5

            industry = row.get("industry", None)
            symbol = row.get("symbol", None)

            conn.execute(
                """INSERT OR REPLACE INTO industry_events
                (event_id, event_type, industry, symbol, title, score, source, published_at, ingested_at,
                 policy_score, sentiment_score, propagated_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    classified["event_type"],
                    industry,
                    symbol,
                    title,
                    round(score, 3),
                    str(row.get("source", "unknown")),
                    published,
                    now,
                    None, None, None,
                ),
            )
            event_count += 1

        conn.commit()

    return {"news_inserted": news_count, "events_inserted": event_count}


if __name__ == "__main__":
    result = fill_news_and_events()
    print(result)
