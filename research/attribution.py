"""Phase 15.4 — 业绩归因

- Brinson：行业 allocation / selection / interaction 分解
- 因子暴露：OLS 回归求 beta，残差为 alpha
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def brinson_attribution(
    portfolio_weights: pd.Series,
    benchmark_weights: pd.Series,
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> dict[str, pd.Series]:
    """Brinson 三因子归因。

    allocation = (Wp - Wb) * Rb
    selection = Wb * (Rp - Rb)
    interaction = (Wp - Wb) * (Rp - Rb)
    """
    sectors = portfolio_weights.index.union(benchmark_weights.index)
    wp = portfolio_weights.reindex(sectors).fillna(0)
    wb = benchmark_weights.reindex(sectors).fillna(0)
    rp = portfolio_returns.reindex(sectors).fillna(0)
    rb = benchmark_returns.reindex(sectors).fillna(0)

    allocation = (wp - wb) * rb
    selection = wb * (rp - rb)
    interaction = (wp - wb) * (rp - rb)
    return {
        "allocation": allocation,
        "selection": selection,
        "interaction": interaction,
    }


def factor_exposure_attribution(
    portfolio_returns: pd.Series,
    factor_returns: pd.DataFrame,
) -> dict:
    """OLS 求因子暴露。

    R_p = alpha + sum(beta_i * F_i) + epsilon
    """
    y = portfolio_returns.values
    X = factor_returns.values
    X_design = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(X_design, y, rcond=None)
    alpha = float(coef[0])
    betas = pd.Series(coef[1:], index=factor_returns.columns)
    pred = X_design @ coef
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "alpha": alpha,
        "exposures": betas,
        "r_squared": r_squared,
    }
