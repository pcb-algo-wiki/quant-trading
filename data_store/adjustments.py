"""Phase 13.1 — 复权因子计算与应用

设计要点：
- 输入：原始（不复权）bars + 公司行为列表
- 输出：与 bars 对齐的 adj_factor 序列（前复权 qfq：最新日 = 1.0，历史日 < 1.0）
- 复权公式（qfq）：
    * 现金分红：ex_date 前 factor *= (close_pre - cash_div) / close_pre
    * 送转股（split_ratio>1）：ex_date 前 factor /= split_ratio
- 后复权（hfq）：第一日 = 1.0，向后累积
- apply：close/open/high/low 全乘 factor，volume 反向除以 factor（保成交额）
"""
from __future__ import annotations

from typing import Literal

import pandas as pd


AdjMode = Literal["qfq", "hfq", "none"]


def compute_adj_factors(
    bars: pd.DataFrame,
    actions: pd.DataFrame,
    mode: AdjMode = "qfq",
) -> pd.Series:
    """计算与 bars 行对齐的复权因子序列。

    Args:
        bars: 必须含 'date'（datetime 或可转）+ 'close'，按日期升序。
        actions: 列含 'ex_date', 'cash_dividend', 'split_ratio'；可空。
        mode: 'qfq' 前复权 / 'hfq' 后复权 / 'none'。

    Returns:
        pd.Series，index 与 bars['date'] 对齐，dtype=float。
    """
    if bars is None or bars.empty:
        return pd.Series([], dtype=float)

    df = bars[["date", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)

    if mode == "none":
        return pd.Series([1.0] * n, index=df["date"])

    factor = [1.0] * n

    if actions is None or actions.empty:
        return pd.Series(factor, index=df["date"])

    acts = actions.copy()
    acts["ex_date"] = pd.to_datetime(acts["ex_date"])
    acts["cash_dividend"] = acts.get("cash_dividend", 0.0).fillna(0.0).astype(float)
    acts["split_ratio"] = acts.get("split_ratio", 1.0).fillna(1.0).astype(float)

    if mode == "qfq":
        # 从最新一天往回算；每遇到一个 ex_date，对其之前（< ex_date）的所有 factor 累乘比例
        for _, act in acts.iterrows():
            ex = act["ex_date"]
            cash = float(act["cash_dividend"])
            ratio = float(act["split_ratio"])
            # 找到 ex_date 前最后一个交易日的 close 作为基准
            pre_mask = df["date"] < ex
            if not pre_mask.any():
                continue
            pre_close = float(df.loc[pre_mask, "close"].iloc[-1])
            if pre_close <= 0:
                continue
            cash_mult = (pre_close - cash) / pre_close if cash > 0 else 1.0
            split_mult = 1.0 / ratio if ratio and ratio != 1.0 else 1.0
            mult = cash_mult * split_mult
            for i in range(n):
                if df.loc[i, "date"] < ex:
                    factor[i] *= mult
        return pd.Series(factor, index=df["date"])

    # hfq：第一天 = 1.0，每个 ex_date 及之后累乘 1/mult
    for _, act in acts.iterrows():
        ex = act["ex_date"]
        cash = float(act["cash_dividend"])
        ratio = float(act["split_ratio"])
        pre_mask = df["date"] < ex
        if not pre_mask.any():
            continue
        pre_close = float(df.loc[pre_mask, "close"].iloc[-1])
        if pre_close <= 0:
            continue
        cash_mult = (pre_close - cash) / pre_close if cash > 0 else 1.0
        split_mult = 1.0 / ratio if ratio and ratio != 1.0 else 1.0
        mult = cash_mult * split_mult
        if mult == 0:
            continue
        for i in range(n):
            if df.loc[i, "date"] >= ex:
                factor[i] /= mult
    return pd.Series(factor, index=df["date"])


def adjust_bars(
    bars: pd.DataFrame,
    factors: pd.Series,
    mode: AdjMode = "qfq",
) -> pd.DataFrame:
    """对 bars 应用复权因子。

    价格列（open/high/low/close）乘以 factor；volume 除以 factor 以保成交额一致。
    mode='none' 直接返回副本。
    """
    out = bars.copy()
    if mode == "none":
        return out

    out["date"] = pd.to_datetime(out["date"])
    f = factors.copy()
    f.index = pd.to_datetime(f.index)
    f_aligned = out["date"].map(f).astype(float).values

    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = out[col].astype(float) * f_aligned
    if "volume" in out.columns:
        # 避免除零
        safe = [v if v else 1.0 for v in f_aligned]
        out["volume"] = out["volume"].astype(float) / safe
    return out
