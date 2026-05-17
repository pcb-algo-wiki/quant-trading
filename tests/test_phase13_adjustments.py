"""Phase 13.1 — 复权与公司行为：schema、repo、复权因子计算

测试覆盖：
1. corporate_actions / adj_factors 表自动建表 + 迁移幂等
2. CorporateActionRepository upsert + 按 symbol 查询
3. AdjFactorRepository upsert + range 查询
4. adjustments.compute_adj_factors 现金分红 + 送转股因子正确
5. adjustments.adjust_bars qfq / hfq / none 三模式
"""
from __future__ import annotations

import pandas as pd

from data_store.db import get_connection
from data_store.repositories import (
    CorporateActionRepository,
    AdjFactorRepository,
)
from data_store.adjustments import compute_adj_factors, adjust_bars


# ---------- schema ----------

def test_phase13_schema_creates_corp_actions_and_adj_factors(tmp_path):
    db_path = tmp_path / "q.db"
    with get_connection(str(db_path)) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('corporate_actions','adj_factors')"
        )
        names = {row[0] for row in cur.fetchall()}
    assert names == {"corporate_actions", "adj_factors"}


def test_phase13_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "q.db"
    # 两次打开应不抛
    with get_connection(str(db_path)) as conn:
        pass
    with get_connection(str(db_path)) as conn:
        cur = conn.execute("PRAGMA table_info(corporate_actions)")
        cols = {row[1] for row in cur.fetchall()}
    assert {"symbol", "ex_date", "action_type", "cash_dividend",
            "split_ratio", "source", "ingested_at"}.issubset(cols)


# ---------- corporate_actions repo ----------

def test_corporate_action_repo_upsert_and_dedup(tmp_path):
    db_path = tmp_path / "q.db"
    df = pd.DataFrame([
        {"symbol": "000001", "ex_date": "2024-06-20", "action_type": "dividend",
         "cash_dividend": 0.345, "split_ratio": 1.0},
        {"symbol": "000001", "ex_date": "2023-05-25", "action_type": "split",
         "cash_dividend": 0.0, "split_ratio": 1.2},  # 每 10 股送 2 股
    ])
    with get_connection(str(db_path)) as conn:
        repo = CorporateActionRepository(conn)
        inserted = repo.upsert_dataframe(source="akshare", actions=df)
        assert inserted == 2

        # 重复插入应去重
        again = repo.upsert_dataframe(source="akshare", actions=df)
        assert again == 0

        rows = repo.fetch(symbol="000001")
        assert len(rows) == 2
        assert rows[0]["ex_date"] == "2023-05-25"  # 升序
        assert rows[1]["cash_dividend"] == 0.345


# ---------- adj_factors repo ----------

def test_adj_factor_repo_upsert_and_range_fetch(tmp_path):
    db_path = tmp_path / "q.db"
    df = pd.DataFrame([
        {"date": "2024-01-02", "adj_factor": 1.0},
        {"date": "2024-06-21", "adj_factor": 0.965},  # 分红后回溯调整
    ])
    with get_connection(str(db_path)) as conn:
        repo = AdjFactorRepository(conn)
        inserted = repo.upsert_dataframe(symbol="000001", source="computed", factors=df)
        assert inserted == 2

        rows = repo.fetch(symbol="000001", start="2024-01-01", end="2024-12-31")
        assert len(rows) == 2
        assert abs(rows[1]["adj_factor"] - 0.965) < 1e-9


# ---------- adjustment math ----------

def test_compute_adj_factors_cash_dividend_only():
    """前复权（qfq）：分红日后所有价格按 (close - cash) / close 比例缩小。

    最新一天因子 = 1.0，向前历史回溯。
    """
    bars = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-19", "2024-06-20", "2024-06-21"]),
        "close": [10.0, 10.0, 9.655],  # ex_date=06-20，含 0.345 现金分红
    })
    actions = pd.DataFrame([
        {"ex_date": "2024-06-20", "cash_dividend": 0.345, "split_ratio": 1.0},
    ])

    factors = compute_adj_factors(bars, actions, mode="qfq")
    # 最新一天 factor=1.0
    assert abs(factors.iloc[-1] - 1.0) < 1e-9
    # ex_date 前一天 factor = (close - cash) / close = 9.655 / 10.0
    assert abs(factors.iloc[0] - 0.9655) < 1e-6
    # ex_date 当天本身就是除权后价，factor = 1.0（与后续保持一致）
    assert abs(factors.iloc[1] - 1.0) < 1e-9


def test_compute_adj_factors_split_only():
    """送股：split_ratio=1.2 即 10 股送 2 股 → 流通股 ×1.2。

    qfq 因子：ex_date 之前 factor /= 1.2
    """
    bars = pd.DataFrame({
        "date": pd.to_datetime(["2023-05-24", "2023-05-25", "2023-05-26"]),
        "close": [12.0, 10.0, 10.0],
    })
    actions = pd.DataFrame([
        {"ex_date": "2023-05-25", "cash_dividend": 0.0, "split_ratio": 1.2},
    ])
    factors = compute_adj_factors(bars, actions, mode="qfq")
    assert abs(factors.iloc[-1] - 1.0) < 1e-9
    assert abs(factors.iloc[0] - (1.0 / 1.2)) < 1e-6


def test_adjust_bars_qfq_applies_factor_to_ohlc():
    bars = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-19", "2024-06-21"]),
        "open": [10.0, 9.6],
        "high": [10.2, 9.8],
        "low": [9.8, 9.5],
        "close": [10.0, 9.655],
        "volume": [1000, 1100],
    })
    factors = pd.Series([0.9655, 1.0], index=bars["date"])
    adj = adjust_bars(bars, factors, mode="qfq")
    # close 列被调整
    assert abs(adj.iloc[0]["close"] - 9.655) < 1e-6
    assert abs(adj.iloc[1]["close"] - 9.655) < 1e-6
    # volume 反向调整以保持成交额一致
    assert abs(adj.iloc[0]["volume"] - 1000 / 0.9655) < 1e-3


def test_adjust_bars_none_mode_returns_unchanged():
    bars = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-19"]),
        "open": [10.0], "high": [10.2], "low": [9.8],
        "close": [10.0], "volume": [1000],
    })
    factors = pd.Series([0.9655], index=bars["date"])
    adj = adjust_bars(bars, factors, mode="none")
    assert abs(adj.iloc[0]["close"] - 10.0) < 1e-9
    assert adj.iloc[0]["volume"] == 1000
