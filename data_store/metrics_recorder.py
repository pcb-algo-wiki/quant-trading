"""Phase 17.2 — 每日指标记录器

落 metrics_daily 表，便于趋势分析与监控仪表盘消费。
"""
from __future__ import annotations

import sqlite3


_DDL = """
CREATE TABLE IF NOT EXISTS metrics_daily (
    date TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, metric_name)
)
"""


class MetricsRecorder:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.execute(_DDL)
        conn.commit()

    def record(self, date: str, metric_name: str, value: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO metrics_daily(date, metric_name, value) VALUES (?,?,?)",
            (date, metric_name, float(value)),
        )
        self.conn.commit()

    def query_range(self, metric_name: str, start: str, end: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT date, metric_name, value FROM metrics_daily "
            "WHERE metric_name=? AND date BETWEEN ? AND ? ORDER BY date",
            (metric_name, start, end),
        )
        return [
            {"date": r[0], "metric_name": r[1], "value": r[2]}
            for r in cur.fetchall()
        ]
