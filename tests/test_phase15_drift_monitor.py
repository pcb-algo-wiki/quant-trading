"""Phase 15.5 — 漂移监控测试"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.drift_monitor import (
    rolling_ic,
    rolling_sharpe,
    detect_drift,
)


def test_rolling_ic_window_size():
    factor = pd.Series(np.arange(100, dtype=float))
    forward_returns = pd.Series(np.arange(100, dtype=float) * 0.01)
    ic = rolling_ic(factor, forward_returns, window=20)
    # 严格正相关，IC 应为 1
    valid = ic.dropna()
    assert (valid > 0.99).all()


def test_rolling_sharpe_higher_for_better_returns():
    rng = np.random.RandomState(0)
    bad = pd.Series(rng.normal(-0.001, 0.01, 100))
    good = pd.Series(rng.normal(0.002, 0.01, 100))
    bad_sr = rolling_sharpe(bad, window=30).dropna()
    good_sr = rolling_sharpe(good, window=30).dropna()
    assert good_sr.mean() > bad_sr.mean()


def test_detect_drift_returns_alert_when_threshold_breached():
    # 后半段收益恶化
    returns = pd.Series(
        list(np.random.RandomState(42).normal(0.002, 0.01, 50))
        + list(np.random.RandomState(42).normal(-0.003, 0.02, 50))
    )
    alerts = detect_drift(
        returns,
        window=20,
        sharpe_threshold=0.0,
        max_drawdown_threshold=-0.05,
    )
    assert isinstance(alerts, list)
    assert len(alerts) > 0
    for a in alerts:
        assert "metric" in a
        assert "value" in a


def test_detect_drift_no_alert_on_healthy_returns():
    rng = np.random.RandomState(0)
    returns = pd.Series(rng.normal(0.003, 0.005, 100))  # 高夏普稳定
    alerts = detect_drift(
        returns,
        window=20,
        sharpe_threshold=0.0,
        max_drawdown_threshold=-0.20,
    )
    assert alerts == []
