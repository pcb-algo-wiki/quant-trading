"""Phase 15.1 — 微观结构约束

A 股回测的最低真实性约束：T+1、涨跌停、停牌。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


@dataclass(frozen=True)
class ConstraintDecision:
    allowed: bool
    reason: str = ""


def enforce_t_plus_one(
    buy_dates: Mapping[str, pd.Timestamp],
    symbol: str,
    current_date: pd.Timestamp,
) -> bool:
    """是否允许在 current_date 卖出 symbol。

    A 股 T+1：买入当日不可卖出。

    Parameters
    ----------
    buy_dates : 已持仓买入日 {symbol: 买入 Timestamp}
    """
    buy_date = buy_dates.get(symbol)
    if buy_date is None:
        return True
    return pd.Timestamp(current_date).normalize() > pd.Timestamp(buy_date).normalize()


class LimitMoveChecker:
    """涨跌停校验（默认 ±10%）。"""

    def __init__(self, limit_pct: float = 0.10, tol: float = 1e-4):
        self.limit_pct = limit_pct
        self.tol = tol

    def is_limit_up(self, prev_close: float, current: float) -> bool:
        if prev_close <= 0:
            return False
        threshold = prev_close * (1 + self.limit_pct)
        return current >= threshold - self.tol

    def is_limit_down(self, prev_close: float, current: float) -> bool:
        if prev_close <= 0:
            return False
        threshold = prev_close * (1 - self.limit_pct)
        return current <= threshold + self.tol


def apply_limit_constraint(
    side: str,
    prev_close: float,
    current_price: float,
    limit_pct: float = 0.10,
) -> ConstraintDecision:
    """涨停日不可买，跌停日不可卖。"""
    checker = LimitMoveChecker(limit_pct=limit_pct)
    if side == "buy" and checker.is_limit_up(prev_close, current_price):
        return ConstraintDecision(False, "涨停板不可买入")
    if side == "sell" and checker.is_limit_down(prev_close, current_price):
        return ConstraintDecision(False, "跌停板不可卖出")
    return ConstraintDecision(True)


class SuspensionChecker:
    """停牌校验。"""

    def __init__(self, suspended_map: Mapping[str, Iterable[pd.Timestamp]]):
        self._map = {
            sym: {pd.Timestamp(d).normalize() for d in days}
            for sym, days in suspended_map.items()
        }

    def is_suspended(self, symbol: str, date: pd.Timestamp) -> bool:
        days = self._map.get(symbol)
        if not days:
            return False
        return pd.Timestamp(date).normalize() in days
