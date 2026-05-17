"""Phase 14.2 — 因子评估框架

核心函数：
- compute_ic_series: 按日期分组算因子 IC（Pearson 或 Spearman）
- summarize_ic: IC 均值 / std / IR / t 统计量 / 正向比例
- compute_factor_decay: 多 horizon 的 IC 衰减分析
- compute_turnover: 因子 rank 换手率

约定：
- 面板数据 long format：每行 (date, symbol, factor, fwd_ret)
- IC = 当日截面 corr(factor, fwd_ret)；至少 3 个 symbol 才有效
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def compute_ic_series(
    panel: pd.DataFrame,
    factor_col: str,
    return_col: str,
    date_col: str = "date",
    method: str = "pearson",
) -> pd.Series:
    """按 date 分组算截面 IC。"""
    out = {}
    for date, grp in panel.groupby(date_col, sort=True):
        f = grp[factor_col]
        r = grp[return_col]
        # 至少 3 个非 NaN 对
        valid = f.notna() & r.notna()
        if valid.sum() < 3:
            out[date] = float("nan")
            continue
        if method == "spearman":
            ic = f[valid].rank().corr(r[valid].rank())
        else:
            ic = f[valid].corr(r[valid])
        out[date] = float(ic) if pd.notna(ic) else float("nan")
    return pd.Series(out, name="ic")


def summarize_ic(ic_series: pd.Series) -> dict:
    """汇总 IC 序列统计量。"""
    s = ic_series.dropna()
    n = len(s)
    if n == 0:
        return {
            "ic_mean": 0.0, "ic_std": 0.0, "ir": 0.0,
            "ic_t_stat": 0.0, "positive_ratio": 0.0, "n": 0,
        }
    mean = float(s.mean())
    std = float(s.std(ddof=1)) if n > 1 else 0.0
    ir = mean / std if std > 0 else 0.0
    t_stat = mean / (std / math.sqrt(n)) if std > 0 else 0.0
    pos_ratio = float((s > 0).sum()) / n
    return {
        "ic_mean": mean,
        "ic_std": std,
        "ir": ir,
        "ic_t_stat": t_stat,
        "positive_ratio": pos_ratio,
        "n": n,
    }


def compute_factor_decay(
    panel: pd.DataFrame,
    factor_col: str,
    return_col: str,
    date_col: str = "date",
    horizons: list[int] | None = None,
) -> dict[int, dict]:
    """衰减分析：对不同 horizon 的 forward return 算 IC summary。

    注意：当前 panel 假设 return_col 已经是单期 forward return；
    多 horizon 评估需调用方提前生成 fwd_ret_h1/h3/h5 等列，
    或这里简化为按 horizon 复用同列做 placeholder（实际研究需扩展）。
    """
    horizons = horizons or [1, 5, 10]
    result = {}
    for h in horizons:
        # 简化版：若没有 horizon 特定列，复用 return_col；
        # 真实场景下应预先 shift(-h) 算出 fwd_ret_h{h}
        col = f"fwd_ret_h{h}" if f"fwd_ret_h{h}" in panel.columns else return_col
        ic = compute_ic_series(panel, factor_col, col, date_col)
        result[h] = summarize_ic(ic)
    return result


def compute_turnover(
    panel: pd.DataFrame,
    date_col: str = "date",
    symbol_col: str = "symbol",
    rank_col: str = "factor_rank",
    top_n: int = 50,
) -> pd.Series:
    """计算 top_n 选股的日间换手率（Jaccard 距离的换手定义）。

    换手率 = |top_t Δ top_{t-1}| / (2 * top_n) ∈ [0, 1]
    """
    dates = sorted(panel[date_col].unique())
    out = {}
    prev_top: set | None = None
    for d in dates:
        grp = panel[panel[date_col] == d]
        # 取 rank 最小的 top_n（rank 越小越优）
        top = set(grp.nsmallest(top_n, rank_col)[symbol_col].tolist())
        if prev_top is not None:
            diff = top.symmetric_difference(prev_top)
            turnover = len(diff) / (2 * top_n)
            out[d] = turnover
        prev_top = top
    return pd.Series(out, name="turnover")
