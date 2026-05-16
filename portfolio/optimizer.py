"""均值-方差 MVO 优化器（scipy SLSQP）

目标：最大化年化 Sharpe 比率（long-only，权重和 = 1）。
当输入不足 2 行时降级为等权。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


class MVOptimizer:
    """最大化 Sharpe 比率的 MVO 优化器。

    Args:
        risk_free_rate: 无风险利率（年化）。
        trading_days: 年化系数（默认 252）。
    """

    def __init__(
        self,
        risk_free_rate: float = 0.0,
        trading_days: int = 252,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.trading_days = trading_days

    def optimize(self, returns: pd.DataFrame) -> dict[str, float]:
        """计算最优权重字典。

        Args:
            returns: T × N 日收益率 DataFrame，列名为策略名。

        Returns:
            {strategy_name: weight}，权重和 = 1，各权重 ∈ [0, 1]。
        """
        n = len(returns.columns)
        equal = {col: 1.0 / n for col in returns.columns}

        if n == 0:
            return {}
        if len(returns) < 2 or n == 1:
            return equal

        try:
            return self._optimize_scipy(returns)
        except Exception:
            return equal

    def _optimize_scipy(self, returns: pd.DataFrame) -> dict[str, float]:
        from scipy.optimize import minimize

        mu = returns.mean().values * self.trading_days
        cov = returns.cov().values * self.trading_days
        rf = self.risk_free_rate
        n = len(mu)

        def neg_sharpe(w: np.ndarray) -> float:
            port_ret = float(w @ mu)
            port_vol = float(np.sqrt(w @ cov @ w))
            if port_vol < 1e-10:
                return 0.0
            return -(port_ret - rf) / port_vol

        x0 = np.ones(n) / n
        bounds = [(0.0, 1.0)] * n
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        result = minimize(
            neg_sharpe,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 500},
        )

        if not result.success:
            # 优化失败降级等权
            n_cols = len(returns.columns)
            return {col: 1.0 / n_cols for col in returns.columns}

        weights = result.x.clip(0.0, 1.0)
        total = weights.sum()
        if total > 1e-10:
            weights /= total

        return dict(zip(returns.columns, weights.tolist()))
