"""Phase 13.3 — 增量数据源 schema + repo

覆盖：
- northbound_flow（北向资金）
- dragon_tiger（龙虎榜个股）
- block_trades（大宗交易）
- etf_holdings（ETF 持仓）
- industry_classification（行业分类映射）
"""
from __future__ import annotations

import pandas as pd

from data_store.db import get_connection
from data_store.repositories import (
    NorthboundFlowRepository,
    DragonTigerRepository,
    BlockTradeRepository,
    EtfHoldingRepository,
    IndustryClassificationRepository,
)


def test_phase13_3_tables_created(tmp_path):
    db_path = tmp_path / "q.db"
    with get_connection(str(db_path)) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('northbound_flow','dragon_tiger','block_trades',"
            "'etf_holdings','industry_classification')"
        )
        names = {row[0] for row in cur.fetchall()}
    assert names == {"northbound_flow", "dragon_tiger", "block_trades",
                     "etf_holdings", "industry_classification"}


def test_northbound_flow_upsert(tmp_path):
    df = pd.DataFrame([
        {"symbol": "000001", "date": "2024-06-19", "hold_shares": 1.0e8,
         "hold_market_cap": 1.0e9, "hold_ratio": 0.05},
        {"symbol": "000001", "date": "2024-06-20", "hold_shares": 1.05e8,
         "hold_market_cap": 1.05e9, "hold_ratio": 0.052},
    ])
    with get_connection(str(tmp_path / "q.db")) as conn:
        repo = NorthboundFlowRepository(conn)
        assert repo.upsert_dataframe(source="akshare", rows=df) == 2
        assert repo.upsert_dataframe(source="akshare", rows=df) == 0
        rows = repo.fetch(symbol="000001")
        assert len(rows) == 2
        assert abs(rows[-1]["hold_ratio"] - 0.052) < 1e-9


def test_dragon_tiger_upsert(tmp_path):
    df = pd.DataFrame([
        {"symbol": "300750", "date": "2024-06-20", "reason": "日涨幅偏离值达7%",
         "buy_amount": 1.2e8, "sell_amount": 0.8e8, "net_amount": 0.4e8},
    ])
    with get_connection(str(tmp_path / "q.db")) as conn:
        repo = DragonTigerRepository(conn)
        assert repo.upsert_dataframe(source="akshare", rows=df) == 1
        assert repo.upsert_dataframe(source="akshare", rows=df) == 0
        rows = repo.fetch(symbol="300750")
        assert rows[0]["reason"].startswith("日涨幅")


def test_block_trades_upsert(tmp_path):
    df = pd.DataFrame([
        {"symbol": "600519", "date": "2024-06-20", "price": 1700.0,
         "volume": 10000, "amount": 1.7e7, "buyer": "中信", "seller": "国君"},
    ])
    with get_connection(str(tmp_path / "q.db")) as conn:
        repo = BlockTradeRepository(conn)
        assert repo.upsert_dataframe(source="akshare", rows=df) == 1
        rows = repo.fetch(symbol="600519")
        assert rows[0]["buyer"] == "中信"


def test_etf_holdings_upsert(tmp_path):
    df = pd.DataFrame([
        {"etf_symbol": "510300", "date": "2024-06-20", "stock_symbol": "600519",
         "weight": 0.061, "shares": 1.2e7},
        {"etf_symbol": "510300", "date": "2024-06-20", "stock_symbol": "601318",
         "weight": 0.054, "shares": 8.5e7},
    ])
    with get_connection(str(tmp_path / "q.db")) as conn:
        repo = EtfHoldingRepository(conn)
        assert repo.upsert_dataframe(source="akshare", rows=df) == 2
        rows = repo.fetch(etf_symbol="510300")
        assert len(rows) == 2


def test_industry_classification_upsert(tmp_path):
    df = pd.DataFrame([
        {"symbol": "600519", "level1": "食品饮料", "level2": "白酒", "level3": "高端白酒",
         "scheme": "申万"},
        {"symbol": "300750", "level1": "电力设备", "level2": "电池", "level3": "锂电池",
         "scheme": "申万"},
    ])
    with get_connection(str(tmp_path / "q.db")) as conn:
        repo = IndustryClassificationRepository(conn)
        assert repo.upsert_dataframe(rows=df) == 2
        # 重复幂等
        assert repo.upsert_dataframe(rows=df) == 0
        rows = repo.fetch(symbol="600519")
        assert rows[0]["level1"] == "食品饮料"
        # 按行业反查
        symbols = repo.fetch_by_industry(level1="食品饮料")
        assert "600519" in [r["symbol"] for r in symbols]
