"""Phase 15.3 — 显著性与过拟合检测

实现：
- Deflated Sharpe Ratio (Bailey & López de Prado, 2014)
- Block Bootstrap 夏普置信区间
- PBO (Probability of Backtest Overfitting)
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats


def _sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    std = returns.std(ddof=1)
    if std == 0:
        return 0.0
    return returns.mean() / std * math.sqrt(periods_per_year)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    num_trials: int,
    periods_per_year: int = 252,
) -> float:
    """计算 DSR 概率值，越接近 1 越显著。

    DSR = Prob(true SR > 0 | observed SR, N trials)
    """
    returns = np.asarray(returns, dtype=float)
    sr_hat = _sharpe(returns, periods_per_year)
    n = len(returns)
    if n < 4:
        return 0.0
    skew = stats.skew(returns)
    kurt = stats.kurtosis(returns, fisher=True)

    # 期望最大 SR（高斯近似）
    gamma = 0.5772156649
    e_max_sr = math.sqrt(
        max(2 * math.log(max(num_trials, 1)), 1e-12)
    ) * (1 - gamma / math.sqrt(2 * math.log(max(num_trials, 2))))

    sr_annual_per_step = sr_hat / math.sqrt(periods_per_year)
    var_sr = (1 - skew * sr_annual_per_step + (kurt) / 4 * sr_annual_per_step ** 2) / (n - 1)
    if var_sr <= 0:
        return 0.0
    z = (sr_annual_per_step - e_max_sr / math.sqrt(periods_per_year)) / math.sqrt(var_sr)
    return float(stats.norm.cdf(z))


def block_bootstrap_sharpe_ci(
    returns: np.ndarray,
    block_size: int = 20,
    n_boot: int = 500,
    ci: float = 0.95,
    periods_per_year: int = 252,
    seed: int | None = None,
) -> tuple[float, float]:
    """块自助法夏普置信区间。"""
    returns = np.asarray(returns, dtype=float)
    n = len(returns)
    if n < block_size * 2:
        return (0.0, 0.0)
    rng = np.random.RandomState(seed)
    n_blocks = (n + block_size - 1) // block_size
    sharpes = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        sample = np.concatenate([returns[s : s + block_size] for s in starts])[:n]
        sharpes[i] = _sharpe(sample, periods_per_year)
    alpha = (1 - ci) / 2
    return (float(np.quantile(sharpes, alpha)), float(np.quantile(sharpes, 1 - alpha)))


def probability_backtest_overfitting(
    returns_matrix: np.ndarray,
    n_splits: int = 16,
) -> float:
    """PBO（López de Prado）：CSCV 简化版。

    returns_matrix : (T, N) — T 期 N 策略每期收益
    """
    arr = np.asarray(returns_matrix, dtype=float)
    T, N = arr.shape
    if N < 2 or T < n_splits * 2:
        return 0.5

    # 切成 n_splits 块
    chunk = T // n_splits
    chunks = [arr[i * chunk : (i + 1) * chunk] for i in range(n_splits)]
    if len(chunks) < 2:
        return 0.5

    from itertools import combinations

    half = n_splits // 2
    losses = 0
    total = 0
    for is_idx in combinations(range(n_splits), half):
        oos_idx = tuple(i for i in range(n_splits) if i not in is_idx)
        is_returns = np.concatenate([chunks[i] for i in is_idx], axis=0)
        oos_returns = np.concatenate([chunks[i] for i in oos_idx], axis=0)
        is_sr = np.array([_sharpe(is_returns[:, j]) for j in range(N)])
        oos_sr = np.array([_sharpe(oos_returns[:, j]) for j in range(N)])
        best_is = int(np.argmax(is_sr))
        # OOS 排名（百分位），越接近 1 越好
        oos_rank = float((oos_sr < oos_sr[best_is]).sum()) / max(N - 1, 1)
        # 若 OOS 表现处于下半，认为过拟合
        if oos_rank < 0.5:
            losses += 1
        total += 1
        # 限制组合数量以避免爆炸
        if total >= 200:
            break
    return losses / total if total else 0.5
