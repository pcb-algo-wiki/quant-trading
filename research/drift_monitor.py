"""Phase 15.5 — 策略漂移监控

滚动 IC、滚动夏普 + 阈值告警。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


def rolling_ic(
    factor: pd.Series,
    forward_returns: pd.Series,
    window: int = 60,
    method: str = "pearson",
) -> pd.Series:
    """滚动相关性 IC。"""
    return factor.rolling(window).corr(forward_returns, method=method) \
        if False else factor.rolling(window).corr(forward_returns)


def rolling_sharpe(
    returns: pd.Series,
    window: int = 60,
    periods_per_year: int = 252,
) -> pd.Series:
    """滚动夏普比率（年化）。"""
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std()
    return (mean / std).where(std > 0) * math.sqrt(periods_per_year)


def _max_drawdown(returns: pd.Series) -> float:
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1).min()
    return float(dd)


def detect_drift(
    returns: pd.Series,
    window: int = 60,
    sharpe_threshold: float = 0.0,
    max_drawdown_threshold: float = -0.10,
    periods_per_year: int = 252,
) -> list[dict]:
    """近 window 期内若夏普 < 阈值 或回撤 < 阈值 → 触发告警。"""
    if len(returns) < window:
        return []
    recent = returns.iloc[-window:]
    sr_series = rolling_sharpe(returns, window=window, periods_per_year=periods_per_year)
    latest_sr = sr_series.iloc[-1]
    dd = _max_drawdown(recent)

    alerts: list[dict] = []
    if pd.notna(latest_sr) and latest_sr < sharpe_threshold:
        alerts.append({
            "metric": "rolling_sharpe",
            "value": float(latest_sr),
            "threshold": sharpe_threshold,
            "window": window,
        })
    if dd < max_drawdown_threshold:
        alerts.append({
            "metric": "max_drawdown",
            "value": dd,
            "threshold": max_drawdown_threshold,
            "window": window,
        })
    return alerts
