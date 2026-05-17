"""Phase 15.1 — 微观结构约束测试"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest.microstructure import (
    LimitMoveChecker,
    SuspensionChecker,
    enforce_t_plus_one,
    apply_limit_constraint,
)


def test_enforce_t_plus_one_blocks_same_day_sell():
    # 买入日 == 卖出日 → 应被拦截
    buy_dates = {"600519": pd.Timestamp("2024-01-15")}
    can_sell = enforce_t_plus_one(buy_dates, "600519", pd.Timestamp("2024-01-15"))
    assert can_sell is False


def test_enforce_t_plus_one_allows_next_day_sell():
    buy_dates = {"600519": pd.Timestamp("2024-01-15")}
    can_sell = enforce_t_plus_one(buy_dates, "600519", pd.Timestamp("2024-01-16"))
    assert can_sell is True


def test_enforce_t_plus_one_unheld_symbol_returns_true():
    can_sell = enforce_t_plus_one({}, "000001", pd.Timestamp("2024-01-16"))
    assert can_sell is True


def test_limit_move_checker_blocks_buy_on_limit_up():
    # 收盘价 = 前收 * 1.10 → 涨停
    checker = LimitMoveChecker(limit_pct=0.10)
    assert checker.is_limit_up(prev_close=10.0, current=11.0) is True
    assert checker.is_limit_up(prev_close=10.0, current=10.5) is False


def test_limit_move_checker_blocks_sell_on_limit_down():
    checker = LimitMoveChecker(limit_pct=0.10)
    assert checker.is_limit_down(prev_close=10.0, current=9.0) is True
    assert checker.is_limit_down(prev_close=10.0, current=9.5) is False


def test_apply_limit_constraint_rejects_buy_on_limit_up():
    decision = apply_limit_constraint(
        side="buy", prev_close=10.0, current_price=11.0, limit_pct=0.10
    )
    assert decision.allowed is False
    assert "涨停" in decision.reason


def test_apply_limit_constraint_rejects_sell_on_limit_down():
    decision = apply_limit_constraint(
        side="sell", prev_close=10.0, current_price=9.0, limit_pct=0.10
    )
    assert decision.allowed is False
    assert "跌停" in decision.reason


def test_apply_limit_constraint_allows_normal_trade():
    decision = apply_limit_constraint(
        side="buy", prev_close=10.0, current_price=10.5, limit_pct=0.10
    )
    assert decision.allowed is True


def test_suspension_checker_rejects_during_suspend():
    suspended = {"600000": [pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-11")]}
    checker = SuspensionChecker(suspended)
    assert checker.is_suspended("600000", pd.Timestamp("2024-01-10")) is True
    assert checker.is_suspended("600000", pd.Timestamp("2024-01-12")) is False
    assert checker.is_suspended("000001", pd.Timestamp("2024-01-10")) is False
