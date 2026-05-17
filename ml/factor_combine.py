"""Phase 14.4 — 因子合成

策略：
- equal_weight: 各因子标准化后等权
- ic_weighted: 用历史 IC 加权
- 输出合成信号 Series，与输入索引对齐
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def zscore_normalize(factor_matrix: pd.DataFrame) -> pd.DataFrame:
    """按列 zscore；NaN 不参与。"""
    out = factor_matrix.copy()
    for col in out.columns:
        s = out[col]
        mean = s.mean(skipna=True)
        std = s.std(skipna=True)
        if std and std > 0:
            out[col] = (s - mean) / std
        else:
            out[col] = 0.0
    return out


def equal_weight_combine(factor_matrix: pd.DataFrame) -> pd.Series:
    """等权合成：标准化后按行均值。"""
    normalized = zscore_normalize(factor_matrix)
    return normalized.mean(axis=1)


def ic_weighted_combine(
    factor_matrix: pd.DataFrame,
    ic_weights: dict[str, float],
) -> pd.Series:
    """IC 加权合成：用历史 IC 作为权重，标准化后线性组合。

    缺失权重的因子忽略；权重做绝对值归一化。
    """
    normalized = zscore_normalize(factor_matrix)
    weights = pd.Series({
        col: ic_weights.get(col, 0.0)
        for col in normalized.columns
    })
    abs_sum = float(weights.abs().sum())
    if abs_sum == 0:
        return pd.Series(np.zeros(len(normalized)), index=normalized.index)
    weights = weights / abs_sum
    return (normalized * weights).sum(axis=1)
