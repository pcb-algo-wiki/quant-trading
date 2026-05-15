import sqlite3
import pandas as pd

from data_store.db import get_connection
from data_store.repositories import MarketBarRepository, NewsRepository, PipelineRunRepository


def test_schema_bootstrap_creates_core_tables(tmp_path):
    db_path = tmp_path / "quant.db"
    with get_connection(str(db_path)) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('market_bars','news_items','policy_items','financial_reports','fund_flow','industry_events','source_documents','pipeline_runs')"
        )
        names = {row[0] for row in cur.fetchall()}

    assert names == {
        "market_bars",
        "news_items",
        "policy_items",
        "financial_reports",
        "fund_flow",
        "industry_events",
        "source_documents",
        "pipeline_runs",
    }


def test_market_bars_upsert_and_query(tmp_path):
    db_path = tmp_path / "quant.db"
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "open": [1.0, 1.1],
            "high": [1.2, 1.3],
            "low": [0.9, 1.0],
            "close": [1.1, 1.2],
            "volume": [1000, 1200],
        }
    )

    with get_connection(str(db_path)) as conn:
        repo = MarketBarRepository(conn)
        inserted = repo.upsert_dataframe(symbol="510300", source="sina", bars=df)
        assert inserted == 2

        inserted_again = repo.upsert_dataframe(symbol="510300", source="sina", bars=df)
        assert inserted_again == 0

        rows = repo.fetch(symbol="510300")
        assert len(rows) == 2
        assert rows[0]["date"] == "2024-01-02"


def test_news_items_hash_dedup(tmp_path):
    db_path = tmp_path / "quant.db"
    df = pd.DataFrame(
        {
            "title": ["同一条新闻", "同一条新闻"],
            "time": ["2024-01-02 09:00:00", "2024-01-02 09:00:00"],
            "url": ["https://example.com/a", "https://example.com/a"],
            "content": ["内容A", "内容A"],
            "情感得分": [0.7, 0.7],
        }
    )

    with get_connection(str(db_path)) as conn:
        repo = NewsRepository(conn)
        inserted = repo.upsert_dataframe(source="eastmoney", news=df)
        assert inserted == 1
        inserted_again = repo.upsert_dataframe(source="eastmoney", news=df)
        assert inserted_again == 0


def test_pipeline_runs_record_status(tmp_path):
    db_path = tmp_path / "quant.db"
    with get_connection(str(db_path)) as conn:
        repo = PipelineRunRepository(conn)
        run_id = repo.start("update_data_store")
        repo.finish(run_id=run_id, status="success")

        row = conn.execute(
            "SELECT pipeline,status,started_at,ended_at FROM pipeline_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()

    assert row[0] == "update_data_store"
    assert row[1] == "success"
    assert row[2] is not None and row[3] is not None
