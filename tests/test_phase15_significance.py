"""Phase 15.3 — 显著性与过拟合检测测试"""
from __future__ import annotations

import numpy as np
import pytest

from research.significance import (
    deflated_sharpe_ratio,
    block_bootstrap_sharpe_ci,
    probability_backtest_overfitting,
)


def test_deflated_sharpe_penalizes_multiple_trials():
    """同样的 SR，试验次数越多 DSR 越小。"""
    returns = np.random.RandomState(42).normal(0.001, 0.01, 252)
    dsr_few = deflated_sharpe_ratio(returns, num_trials=5)
    dsr_many = deflated_sharpe_ratio(returns, num_trials=500)
    assert dsr_few > dsr_many


def test_deflated_sharpe_returns_probability_in_range():
    returns = np.random.RandomState(0).normal(0.002, 0.01, 252)
    dsr = deflated_sharpe_ratio(returns, num_trials=10)
    assert 0.0 <= dsr <= 1.0


def test_block_bootstrap_sharpe_ci_returns_lower_upper():
    rng = np.random.RandomState(7)
    returns = rng.normal(0.001, 0.01, 500)
    lower, upper = block_bootstrap_sharpe_ci(
        returns, block_size=20, n_boot=200, ci=0.95
    )
    assert lower < upper


def test_pbo_returns_value_in_unit_interval():
    """PBO 应在 [0,1]。"""
    rng = np.random.RandomState(11)
    # 100 个策略 × 200 日收益
    matrix = rng.normal(0, 0.01, (200, 100))
    pbo = probability_backtest_overfitting(matrix, n_splits=8)
    assert 0.0 <= pbo <= 1.0


def test_pbo_high_when_strategies_are_pure_noise():
    """纯噪声策略，PBO 应较高（约 0.5）。"""
    rng = np.random.RandomState(13)
    matrix = rng.normal(0, 0.01, (300, 50))
    pbo = probability_backtest_overfitting(matrix, n_splits=10)
    assert pbo > 0.3  # 噪声场景应明显偏高
