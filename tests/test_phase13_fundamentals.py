"""Phase 13.2 — 基本面深度扩展

通过 PRAGMA + ALTER TABLE 幂等迁移给 financial_reports 增加：
  operating_cash_flow, free_cash_flow, capex,
  total_assets, total_equity, roe, roic
并提供 FinancialReportRepository 完成 upsert + 按 symbol 查询。
"""
from __future__ import annotations

import pandas as pd

from data_store.db import get_connection
from data_store.repositories import FinancialReportRepository


def test_financial_reports_has_extended_columns(tmp_path):
    db_path = tmp_path / "q.db"
    with get_connection(str(db_path)) as conn:
        cur = conn.execute("PRAGMA table_info(financial_reports)")
        cols = {row[1] for row in cur.fetchall()}
    expected = {
        "symbol", "report_period", "revenue", "net_profit", "gross_margin",
        "rd_expense", "operating_cash_flow", "free_cash_flow", "capex",
        "total_assets", "total_equity", "roe", "roic", "source", "ingested_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_migrations_idempotent_on_existing_db(tmp_path):
    db_path = tmp_path / "q.db"
    # 先打开一次创建表
    with get_connection(str(db_path)) as conn:
        pass
    # 再次打开不应失败
    with get_connection(str(db_path)) as conn:
        cur = conn.execute("PRAGMA table_info(financial_reports)")
        cols = {row[1] for row in cur.fetchall()}
    assert "roe" in cols and "free_cash_flow" in cols


def test_financial_report_repo_upsert_and_fetch(tmp_path):
    db_path = tmp_path / "q.db"
    df = pd.DataFrame([
        {"symbol": "000001", "report_period": "2024Q1", "revenue": 1000,
         "net_profit": 100, "roe": 0.12, "free_cash_flow": 80, "capex": 30},
        {"symbol": "000001", "report_period": "2024Q2", "revenue": 1200,
         "net_profit": 130, "roe": 0.14, "free_cash_flow": 100, "capex": 35},
    ])
    with get_connection(str(db_path)) as conn:
        repo = FinancialReportRepository(conn)
        inserted = repo.upsert_dataframe(source="akshare", reports=df)
        assert inserted == 2
        assert repo.upsert_dataframe(source="akshare", reports=df) == 0
        rows = repo.fetch(symbol="000001")
        assert len(rows) == 2
        assert rows[0]["report_period"] == "2024Q1"
        assert abs(rows[1]["roe"] - 0.14) < 1e-9
