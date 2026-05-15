from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

import pandas as pd
import sqlite3


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _to_date_str(value: Any) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


class MarketBarRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_dataframe(self, symbol: str, source: str, bars: pd.DataFrame) -> int:
        if bars is None or bars.empty:
            return 0

        inserted = 0
        sql = """
        INSERT OR IGNORE INTO market_bars
        (symbol, date, open, high, low, close, volume, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        now = _now()
        for _, row in bars.iterrows():
            cur = self.conn.execute(
                sql,
                (
                    symbol,
                    _to_date_str(row["date"]),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]),
                    source,
                    now,
                ),
            )
            inserted += cur.rowcount
        return inserted

    def fetch(self, symbol: str, source: str | None = None) -> list[dict]:
        if source:
            cur = self.conn.execute(
                """
                SELECT symbol, date, open, high, low, close, volume, source
                FROM market_bars
                WHERE symbol = ? AND source = ?
                ORDER BY date
                """,
                (symbol, source),
            )
        else:
            cur = self.conn.execute(
                """
                SELECT symbol, date, open, high, low, close, volume, source
                FROM market_bars
                WHERE symbol = ?
                ORDER BY date
                """,
                (symbol,),
            )
        return [dict(row) for row in cur.fetchall()]


class NewsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _hash_record(title: str, published_at: str, url: str, content: str) -> str:
        raw = f"{title}|{published_at}|{url}|{content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def upsert_dataframe(self, source: str, news: pd.DataFrame) -> int:
        if news is None or news.empty:
            return 0

        inserted = 0
        sql = """
        INSERT OR IGNORE INTO news_items
        (source, title, published_at, url, content, content_hash, sentiment, related_symbol, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        now = _now()
        for _, row in news.iterrows():
            title = str(row.get("title", "") or "")
            if not title:
                title = str(row.get("新闻标题", "") or "")
            published = str(row.get("time", "") or row.get("发布时间", "") or now)
            url = str(row.get("url", "") or row.get("新闻链接", "") or "")
            content = str(row.get("content", "") or row.get("新闻内容", "") or "")
            sentiment = row.get("情感得分", row.get("sentiment", None))
            content_hash = self._hash_record(title=title, published_at=published, url=url, content=content)

            cur = self.conn.execute(
                sql,
                (
                    source,
                    title,
                    published,
                    url,
                    content,
                    content_hash,
                    float(sentiment) if sentiment is not None else None,
                    row.get("related_symbol", None),
                    now,
                ),
            )
            inserted += cur.rowcount
        return inserted


class PipelineRunRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def start(self, pipeline: str) -> str:
        run_id = uuid.uuid4().hex
        self.conn.execute(
            """
            INSERT INTO pipeline_runs (run_id, pipeline, status, started_at, ended_at, error)
            VALUES (?, ?, ?, ?, NULL, NULL)
            """,
            (run_id, pipeline, "running", _now()),
        )
        return run_id

    def finish(self, run_id: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE pipeline_runs
            SET status = ?, ended_at = ?, error = ?
            WHERE run_id = ?
            """,
            (status, _now(), error, run_id),
        )
