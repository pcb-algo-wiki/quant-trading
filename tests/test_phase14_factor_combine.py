"""Phase 14.4 — 因子合成测试"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.factor_combine import zscore_normalize, equal_weight_combine, ic_weighted_combine


def test_zscore_normalize_zero_mean_unit_std():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]})
    out = zscore_normalize(df)
    assert abs(out["a"].mean()) < 1e-9
    assert abs(out["a"].std(ddof=1) - 1.0) < 1e-6
    assert abs(out["b"].mean()) < 1e-9


def test_zscore_normalize_handles_constant_column():
    df = pd.DataFrame({"const": [5.0] * 4})
    out = zscore_normalize(df)
    # 常数列 std=0，全置 0
    assert (out["const"] == 0.0).all()


def test_equal_weight_combine_averages_normalized():
    df = pd.DataFrame({"f1": [1, 2, 3, 4, 5], "f2": [5, 4, 3, 2, 1]})
    sig = equal_weight_combine(df)
    # f1+f2 互为相反的标准化值，等权和应近 0
    assert abs(sig.mean()) < 1e-9
    assert (sig.abs() < 1e-9).all()


def test_ic_weighted_combine_respects_weights():
    df = pd.DataFrame({"f1": [1.0, 2.0, 3.0], "f2": [3.0, 2.0, 1.0]})
    # f1 权重 1，f2 权重 0：结果完全由 f1 决定
    sig = ic_weighted_combine(df, ic_weights={"f1": 1.0, "f2": 0.0})
    # f1 标准化升序，故 sig 升序
    assert sig.iloc[0] < sig.iloc[-1]


def test_ic_weighted_combine_missing_weights_default_zero():
    df = pd.DataFrame({"f1": [1.0, 2.0, 3.0], "f2": [3.0, 2.0, 1.0]})
    sig = ic_weighted_combine(df, ic_weights={})  # 全 0 权重
    assert (sig == 0).all()
