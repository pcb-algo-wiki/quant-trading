"""Phase 13.4 — 数据 lineage 与健康监控

覆盖：
- data_provenance 表（每次写入留 trace）
- DataProvenanceRepository 记录写入元数据
- data_health.compute_health_report(conn) 输出每数据集统计：
    * 行数、symbol 数、最新日期、滞后天数、来源分布
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from data_store.db import get_connection
from data_store.repositories import (
    MarketBarRepository,
    DataProvenanceRepository,
)
from data_store.data_health import compute_health_report


def test_data_provenance_table_created(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='data_provenance'"
        )
        assert cur.fetchone() is not None


def test_data_provenance_record_run(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        repo = DataProvenanceRepository(conn)
        prov_id = repo.record(
            dataset="market_bars",
            source="akshare",
            symbol_count=3,
            row_count=600,
            pipeline_run_id="run-xyz",
            extra={"start": "2024-01-01", "end": "2024-06-30"},
        )
        assert prov_id
        rows = repo.fetch(dataset="market_bars")
        assert len(rows) == 1
        assert rows[0]["source"] == "akshare"
        assert rows[0]["row_count"] == 600


def test_health_report_computes_lag_and_counts(tmp_path):
    db_path = tmp_path / "q.db"
    today = datetime.utcnow().date()
    df = pd.DataFrame({
        "date": pd.to_datetime([today - timedelta(days=10), today - timedelta(days=3)]),
        "open": [10.0, 11.0],
        "high": [10.5, 11.5],
        "low": [9.5, 10.5],
        "close": [10.2, 11.2],
        "volume": [1000, 1100],
    })
    with get_connection(str(db_path)) as conn:
        bars = MarketBarRepository(conn)
        bars.upsert_dataframe(symbol="510300", source="akshare", bars=df)

        report = compute_health_report(conn)

    # 至少有 market_bars 这一项
    assert "market_bars" in report
    mb = report["market_bars"]
    assert mb["row_count"] == 2
    assert mb["symbol_count"] == 1
    assert mb["latest_date"] == str(today - timedelta(days=3))
    assert mb["lag_days"] == 3
    assert mb["sources"] == {"akshare": 2}


def test_health_report_handles_empty_tables(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        report = compute_health_report(conn)
    # 空表也应返回结构
    assert "market_bars" in report
    assert report["market_bars"]["row_count"] == 0
    assert report["market_bars"]["latest_date"] is None
