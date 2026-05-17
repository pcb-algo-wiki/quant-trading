"""Phase 14.1 — 因子库（factor library）测试

设计要点：
- BaseFactor 抽象基类：name, category, compute(price_df) -> pd.Series
- FactorRegistry：注册 / 查询 / 按类别列出 / 批量计算成因子矩阵
- 内置 12+ 标准因子（动量/反转/波动率/成交量/量价背离）
- 基本面因子从 financial_reports + market_bars 联合计算（pe/pb/roe_rank/profit_growth）
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.factors.base import BaseFactor, FactorRegistry
from ml.factors.builtins import register_default_factors


@pytest.fixture
def price_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 90
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    })


def test_base_factor_protocol(price_df):
    class DummyFactor(BaseFactor):
        name = "dummy"
        category = "test"

        def compute(self, price_df: pd.DataFrame) -> pd.Series:
            return price_df["close"].pct_change(1)

    f = DummyFactor()
    s = f.compute(price_df)
    assert isinstance(s, pd.Series)
    assert len(s) == len(price_df)


def test_factory_registry_register_and_lookup():
    reg = FactorRegistry()

    class F1(BaseFactor):
        name = "f1"
        category = "momentum"
        def compute(self, df): return df["close"].pct_change(5)

    class F2(BaseFactor):
        name = "f2"
        category = "volatility"
        def compute(self, df): return df["close"].pct_change().rolling(10).std()

    reg.register(F1())
    reg.register(F2())

    assert reg.get("f1").name == "f1"
    assert set(reg.list_names()) == {"f1", "f2"}
    assert reg.list_by_category("momentum") == ["f1"]

    with pytest.raises(KeyError):
        reg.get("nonexistent")


def test_compute_factor_matrix(price_df):
    reg = FactorRegistry()

    class FA(BaseFactor):
        name = "ret5"
        category = "momentum"
        def compute(self, df): return df["close"].pct_change(5)

    class FB(BaseFactor):
        name = "vol10"
        category = "volatility"
        def compute(self, df): return df["close"].pct_change().rolling(10).std()

    reg.register(FA())
    reg.register(FB())

    matrix = reg.compute_matrix(price_df)
    assert isinstance(matrix, pd.DataFrame)
    assert set(matrix.columns) == {"ret5", "vol10"}
    assert len(matrix) == len(price_df)


def test_default_factor_library_has_minimum_coverage(price_df):
    reg = FactorRegistry()
    register_default_factors(reg)
    # 至少 12 个内置因子，覆盖 4 个类别
    names = reg.list_names()
    assert len(names) >= 12
    cats = {reg.get(n).category for n in names}
    assert {"momentum", "reversal", "volatility", "volume"}.issubset(cats)


def test_default_factors_compute_without_error(price_df):
    reg = FactorRegistry()
    register_default_factors(reg)
    matrix = reg.compute_matrix(price_df)
    assert matrix.shape[1] == len(reg.list_names())
    # 至少最后一行有有效数据（除 NaN 行）
    last_valid = matrix.dropna().tail(1)
    assert len(last_valid) >= 1
