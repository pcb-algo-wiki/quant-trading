"""Phase 14.2 — 因子评估框架（IC / IR / 衰减 / 换手率）"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.factor_eval import (
    compute_ic_series,
    summarize_ic,
    compute_factor_decay,
    compute_turnover,
)


@pytest.fixture
def panel_data():
    """构造 5 只股票 x 50 天的 factor + forward_return 面板。"""
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", periods=50)
    symbols = [f"S{i}" for i in range(5)]
    rows = []
    for d in dates:
        for s in symbols:
            factor = rng.normal()
            # 有正相关性的 forward return
            fwd_ret = 0.6 * factor + rng.normal(0, 0.5)
            rows.append({"date": d, "symbol": s, "factor": factor, "fwd_ret": fwd_ret})
    return pd.DataFrame(rows)


def test_compute_ic_series_returns_per_date(panel_data):
    ic = compute_ic_series(panel_data, factor_col="factor", return_col="fwd_ret",
                            date_col="date", method="pearson")
    assert isinstance(ic, pd.Series)
    # 每个 date 一个 IC 值（5 个 symbol 可算相关）
    assert len(ic) == 50
    # 因为生成时强正相关，平均 IC 显著为正
    assert ic.mean() > 0.3


def test_summarize_ic_returns_metrics(panel_data):
    ic = compute_ic_series(panel_data, "factor", "fwd_ret", "date")
    summary = summarize_ic(ic)
    assert "ic_mean" in summary and "ic_std" in summary and "ir" in summary
    assert "ic_t_stat" in summary and "positive_ratio" in summary
    assert summary["ir"] > 0
    assert 0 <= summary["positive_ratio"] <= 1


def test_factor_decay_returns_ic_for_each_horizon(panel_data):
    # 把 panel 转成 wide 价格形式以测试 decay
    decay = compute_factor_decay(
        panel_data, factor_col="factor", return_col="fwd_ret",
        date_col="date", horizons=[1, 3, 5],
    )
    assert set(decay.keys()) == {1, 3, 5}
    for h in [1, 3, 5]:
        assert "ic_mean" in decay[h]


def test_compute_turnover_measures_position_change():
    # 构造 3 天 x 5 symbol 的 rank 变化
    dates = pd.date_range("2024-01-01", periods=3)
    syms = ["A", "B", "C", "D", "E"]
    data = []
    # 第 1 天 rank: A,B,C,D,E
    # 第 2 天 rank: 全反转
    # 第 3 天 rank: 与第 2 天相同（换手 0）
    ranks = [[1, 2, 3, 4, 5], [5, 4, 3, 2, 1], [5, 4, 3, 2, 1]]
    for d, r in zip(dates, ranks):
        for s, rk in zip(syms, r):
            data.append({"date": d, "symbol": s, "factor_rank": rk})
    df = pd.DataFrame(data)
    turnover = compute_turnover(df, date_col="date", symbol_col="symbol",
                                  rank_col="factor_rank", top_n=2)
    # 第 1->2 天：top 2 从 {A,B} 变 {D,E}，换手 100%
    # 第 2->3 天：相同，换手 0
    assert abs(turnover.iloc[0] - 1.0) < 1e-9
    assert abs(turnover.iloc[1] - 0.0) < 1e-9
