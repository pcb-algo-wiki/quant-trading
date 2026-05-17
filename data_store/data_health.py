"""Phase 13.4 — 数据健康监控

为核心数据集生成统计快照：
- row_count：总行数
- symbol_count：去重 symbol 数
- latest_date：最新日期（YYYY-MM-DD）
- lag_days：距今滞后天数（基于 UTC date）
- sources：来源分布 {source: count}

输入：sqlite3 connection
输出：dict[dataset_name, dict]
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional


# (table, symbol_col, date_col, source_col)
_DATASETS: list[tuple[str, Optional[str], Optional[str], Optional[str]]] = [
    ("market_bars",        "symbol",       "date",         "source"),
    ("news_items",         "related_symbol", "published_at","source"),
    ("policy_items",       None,           "published_at",  "source"),
    ("financial_reports",  "symbol",       "report_period", "source"),
    ("fund_flow",          "symbol",       "date",          "source"),
    ("industry_events",    "symbol",       "published_at",  "source"),
    ("northbound_flow",    "symbol",       "date",          "source"),
    ("dragon_tiger",       "symbol",       "date",          "source"),
    ("block_trades",       "symbol",       "date",          "source"),
    ("etf_holdings",       "etf_symbol",   "date",          "source"),
    ("corporate_actions",  "symbol",       "ex_date",       "source"),
    ("adj_factors",        "symbol",       "date",          "source"),
]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def _lag_days(latest: str | None) -> int | None:
    if not latest:
        return None
    try:
        # date 字段统一截前 10 位
        dt = datetime.strptime(latest[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = datetime.utcnow().date()
    return (today - dt).days


def compute_health_report(conn: sqlite3.Connection) -> dict[str, dict]:
    report: dict[str, dict] = {}
    for table, symbol_col, date_col, source_col in _DATASETS:
        if not _table_exists(conn, table):
            continue
        item: dict = {"row_count": 0, "symbol_count": 0,
                      "latest_date": None, "lag_days": None, "sources": {}}

        row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        item["row_count"] = row_count

        if row_count and symbol_col:
            item["symbol_count"] = conn.execute(
                f"SELECT COUNT(DISTINCT {symbol_col}) FROM {table}"
            ).fetchone()[0]

        if row_count and date_col:
            latest = conn.execute(
                f"SELECT MAX({date_col}) FROM {table}"
            ).fetchone()[0]
            if latest:
                item["latest_date"] = str(latest)[:10]
                item["lag_days"] = _lag_days(latest)

        if row_count and source_col:
            cur = conn.execute(
                f"SELECT {source_col}, COUNT(*) FROM {table} GROUP BY {source_col}"
            )
            item["sources"] = {row[0]: row[1] for row in cur.fetchall() if row[0]}

        report[table] = item
    return report


def format_health_report(report: dict[str, dict]) -> str:
    """生成可读 markdown 报告。"""
    lines = ["# 数据健康日报", ""]
    lines.append("| 数据集 | 行数 | symbol 数 | 最新日 | 滞后(天) | 来源 |")
    lines.append("|--------|------|----------|--------|---------|------|")
    for ds, info in report.items():
        sources = ", ".join(f"{k}:{v}" for k, v in (info["sources"] or {}).items())
        lines.append(
            f"| {ds} | {info['row_count']} | {info['symbol_count']} | "
            f"{info['latest_date'] or '-'} | {info['lag_days'] if info['lag_days'] is not None else '-'} | "
            f"{sources or '-'} |"
        )
    return "\n".join(lines)
