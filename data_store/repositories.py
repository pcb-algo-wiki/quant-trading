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


class CorporateActionRepository:
    """公司行为（分红/送转/配股）。

    action_type: 'dividend' | 'split' | 'rights'
    cash_dividend: 每股现金分红（税前）
    split_ratio: 除权后流通股扩张比例（送 2 股 → 1.2）
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_dataframe(self, source: str, actions: pd.DataFrame) -> int:
        if actions is None or actions.empty:
            return 0
        sql = """
        INSERT OR IGNORE INTO corporate_actions
        (symbol, ex_date, action_type, cash_dividend, split_ratio, source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        now = _now()
        inserted = 0
        for _, row in actions.iterrows():
            cur = self.conn.execute(
                sql,
                (
                    str(row["symbol"]),
                    _to_date_str(row["ex_date"]),
                    str(row["action_type"]),
                    float(row.get("cash_dividend", 0.0) or 0.0),
                    float(row.get("split_ratio", 1.0) or 1.0),
                    source,
                    now,
                ),
            )
            inserted += cur.rowcount
        return inserted

    def fetch(self, symbol: str) -> list[dict]:
        cur = self.conn.execute(
            """
            SELECT symbol, ex_date, action_type, cash_dividend, split_ratio, source
            FROM corporate_actions
            WHERE symbol = ?
            ORDER BY ex_date
            """,
            (symbol,),
        )
        return [dict(row) for row in cur.fetchall()]


class AdjFactorRepository:
    """复权因子缓存表（按 symbol+date+source 唯一）。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_dataframe(self, symbol: str, source: str, factors: pd.DataFrame) -> int:
        if factors is None or factors.empty:
            return 0
        sql = """
        INSERT OR REPLACE INTO adj_factors
        (symbol, date, adj_factor, source, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """
        now = _now()
        # 用 SELECT changes() 判定新增 vs 替换不靠谱，先查存量再插入
        existing = {
            row[0]
            for row in self.conn.execute(
                "SELECT date FROM adj_factors WHERE symbol = ? AND source = ?",
                (symbol, source),
            ).fetchall()
        }
        inserted = 0
        for _, row in factors.iterrows():
            date_str = _to_date_str(row["date"])
            self.conn.execute(
                sql,
                (symbol, date_str, float(row["adj_factor"]), source, now),
            )
            if date_str not in existing:
                inserted += 1
        return inserted

    def fetch(self, symbol: str, start: str | None = None, end: str | None = None) -> list[dict]:
        sql = "SELECT symbol, date, adj_factor, source FROM adj_factors WHERE symbol = ?"
        params: list = [symbol]
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY date"
        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


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


# ===== Phase 13.2 — 基本面 =====

class FinancialReportRepository:
    FIELDS = (
        "revenue", "net_profit", "gross_margin", "rd_expense",
        "operating_cash_flow", "free_cash_flow", "capex",
        "total_assets", "total_equity", "roe", "roic",
    )

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_dataframe(self, source: str, reports: pd.DataFrame) -> int:
        if reports is None or reports.empty:
            return 0
        cols = ["symbol", "report_period", *self.FIELDS, "source", "ingested_at"]
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT OR IGNORE INTO financial_reports ({','.join(cols)}) VALUES ({placeholders})"
        now = _now()
        inserted = 0
        for _, row in reports.iterrows():
            values = [str(row["symbol"]), str(row["report_period"])]
            for f in self.FIELDS:
                v = row.get(f)
                values.append(float(v) if v is not None and not pd.isna(v) else None)
            values.extend([source, now])
            cur = self.conn.execute(sql, values)
            inserted += cur.rowcount
        return inserted

    def fetch(self, symbol: str) -> list[dict]:
        cur = self.conn.execute(
            f"SELECT symbol, report_period, {','.join(self.FIELDS)}, source "
            "FROM financial_reports WHERE symbol = ? ORDER BY report_period",
            (symbol,),
        )
        return [dict(row) for row in cur.fetchall()]


# ===== Phase 13.3 — 增量数据源 =====

class _GenericUpsertRepo:
    """通用 INSERT OR IGNORE 工具，子类指定 TABLE / COLUMNS / KEY_FIELDS。"""
    TABLE: str = ""
    COLUMNS: tuple[str, ...] = ()
    DATE_FIELDS: tuple[str, ...] = ()
    HAS_SOURCE: bool = True
    HAS_INGESTED: bool = True

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _coerce(self, field: str, value: Any) -> Any:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if field in self.DATE_FIELDS:
            return _to_date_str(value)
        return value

    def upsert_dataframe(self, rows: pd.DataFrame, source: str | None = None) -> int:
        if rows is None or rows.empty:
            return 0
        all_cols = list(self.COLUMNS)
        if self.HAS_SOURCE:
            all_cols.append("source")
        if self.HAS_INGESTED:
            all_cols.append("ingested_at")
        placeholders = ",".join(["?"] * len(all_cols))
        sql = f"INSERT OR IGNORE INTO {self.TABLE} ({','.join(all_cols)}) VALUES ({placeholders})"
        now = _now()
        inserted = 0
        for _, row in rows.iterrows():
            values = [self._coerce(c, row.get(c)) for c in self.COLUMNS]
            if self.HAS_SOURCE:
                values.append(source or "unknown")
            if self.HAS_INGESTED:
                values.append(now)
            cur = self.conn.execute(sql, values)
            inserted += cur.rowcount
        return inserted


class NorthboundFlowRepository(_GenericUpsertRepo):
    TABLE = "northbound_flow"
    COLUMNS = ("symbol", "date", "hold_shares", "hold_market_cap", "hold_ratio")
    DATE_FIELDS = ("date",)

    def upsert_dataframe(self, rows: pd.DataFrame, source: str | None = None) -> int:  # type: ignore[override]
        return super().upsert_dataframe(rows, source=source)

    def fetch(self, symbol: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT symbol, date, hold_shares, hold_market_cap, hold_ratio, source "
            "FROM northbound_flow WHERE symbol = ? ORDER BY date",
            (symbol,),
        )
        return [dict(row) for row in cur.fetchall()]


class DragonTigerRepository(_GenericUpsertRepo):
    TABLE = "dragon_tiger"
    COLUMNS = ("symbol", "date", "reason", "buy_amount", "sell_amount", "net_amount")
    DATE_FIELDS = ("date",)

    def fetch(self, symbol: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT symbol, date, reason, buy_amount, sell_amount, net_amount, source "
            "FROM dragon_tiger WHERE symbol = ? ORDER BY date",
            (symbol,),
        )
        return [dict(row) for row in cur.fetchall()]


class BlockTradeRepository(_GenericUpsertRepo):
    TABLE = "block_trades"
    COLUMNS = ("symbol", "date", "price", "volume", "amount", "buyer", "seller")
    DATE_FIELDS = ("date",)

    def fetch(self, symbol: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT symbol, date, price, volume, amount, buyer, seller, source "
            "FROM block_trades WHERE symbol = ? ORDER BY date",
            (symbol,),
        )
        return [dict(row) for row in cur.fetchall()]


class EtfHoldingRepository(_GenericUpsertRepo):
    TABLE = "etf_holdings"
    COLUMNS = ("etf_symbol", "date", "stock_symbol", "weight", "shares")
    DATE_FIELDS = ("date",)

    def fetch(self, etf_symbol: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT etf_symbol, date, stock_symbol, weight, shares, source "
            "FROM etf_holdings WHERE etf_symbol = ? ORDER BY date, stock_symbol",
            (etf_symbol,),
        )
        return [dict(row) for row in cur.fetchall()]


class IndustryClassificationRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_dataframe(self, rows: pd.DataFrame) -> int:
        if rows is None or rows.empty:
            return 0
        sql = """
        INSERT OR IGNORE INTO industry_classification
        (symbol, scheme, level1, level2, level3, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        now = _now()
        inserted = 0
        for _, row in rows.iterrows():
            cur = self.conn.execute(
                sql,
                (
                    str(row["symbol"]),
                    str(row.get("scheme", "default") or "default"),
                    row.get("level1"),
                    row.get("level2"),
                    row.get("level3"),
                    now,
                ),
            )
            inserted += cur.rowcount
        return inserted

    def fetch(self, symbol: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT symbol, scheme, level1, level2, level3 "
            "FROM industry_classification WHERE symbol = ?",
            (symbol,),
        )
        return [dict(row) for row in cur.fetchall()]

    def fetch_by_industry(self, level1: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT symbol, scheme, level1, level2, level3 "
            "FROM industry_classification WHERE level1 = ?",
            (level1,),
        )
        return [dict(row) for row in cur.fetchall()]


# ===== Phase 13.4 — data lineage =====

class DataProvenanceRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(
        self,
        dataset: str,
        source: str,
        symbol_count: int | None = None,
        row_count: int | None = None,
        pipeline_run_id: str | None = None,
        extra: dict | None = None,
    ) -> str:
        import json
        prov_id = uuid.uuid4().hex
        self.conn.execute(
            """
            INSERT INTO data_provenance
            (prov_id, dataset, source, symbol_count, row_count, pipeline_run_id, extra_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prov_id, dataset, source,
                symbol_count, row_count, pipeline_run_id,
                json.dumps(extra, ensure_ascii=False) if extra else None,
                _now(),
            ),
        )
        return prov_id

    def fetch(self, dataset: str | None = None) -> list[dict]:
        if dataset:
            cur = self.conn.execute(
                "SELECT prov_id, dataset, source, symbol_count, row_count, "
                "pipeline_run_id, extra_json, created_at "
                "FROM data_provenance WHERE dataset = ? ORDER BY created_at DESC",
                (dataset,),
            )
        else:
            cur = self.conn.execute(
                "SELECT prov_id, dataset, source, symbol_count, row_count, "
                "pipeline_run_id, extra_json, created_at "
                "FROM data_provenance ORDER BY created_at DESC"
            )
        return [dict(row) for row in cur.fetchall()]
