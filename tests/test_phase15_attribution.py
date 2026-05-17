"""Phase 15.4 — 业绩归因测试"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.attribution import (
    brinson_attribution,
    factor_exposure_attribution,
)


def test_brinson_attribution_returns_three_components():
    portfolio_weights = pd.Series({"sector_A": 0.6, "sector_B": 0.4})
    benchmark_weights = pd.Series({"sector_A": 0.5, "sector_B": 0.5})
    portfolio_returns = pd.Series({"sector_A": 0.10, "sector_B": 0.05})
    benchmark_returns = pd.Series({"sector_A": 0.08, "sector_B": 0.06})

    result = brinson_attribution(
        portfolio_weights, benchmark_weights,
        portfolio_returns, benchmark_returns,
    )

    assert "allocation" in result
    assert "selection" in result
    assert "interaction" in result
    # 总和 ≈ 组合收益 - 基准收益
    total = result["allocation"].sum() + result["selection"].sum() + result["interaction"].sum()
    expected = (portfolio_weights * portfolio_returns).sum() - (benchmark_weights * benchmark_returns).sum()
    assert abs(total - expected) < 1e-9


def test_brinson_zero_when_portfolio_equals_benchmark():
    weights = pd.Series({"A": 0.5, "B": 0.5})
    returns = pd.Series({"A": 0.05, "B": 0.03})
    result = brinson_attribution(weights, weights, returns, returns)
    assert abs(result["allocation"].sum()) < 1e-9
    assert abs(result["selection"].sum()) < 1e-9


def test_factor_exposure_attribution_recovers_betas():
    """已知因子和暴露，残差应近 0。"""
    rng = np.random.RandomState(42)
    n = 200
    factor_returns = pd.DataFrame({
        "mkt": rng.normal(0.001, 0.01, n),
        "size": rng.normal(0, 0.005, n),
    })
    # 真实暴露
    true_beta = pd.Series({"mkt": 1.2, "size": -0.3})
    portfolio_returns = factor_returns.dot(true_beta) + rng.normal(0, 0.0001, n)

    result = factor_exposure_attribution(portfolio_returns, factor_returns)
    assert abs(result["exposures"]["mkt"] - 1.2) < 0.05
    assert abs(result["exposures"]["size"] - (-0.3)) < 0.05
    assert "alpha" in result
    assert "r_squared" in result
    assert result["r_squared"] > 0.95
