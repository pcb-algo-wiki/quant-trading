#!/usr/bin/env python3
"""分段BH分析"""
import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")
import pandas as pd
import numpy as np
from pathlib import Path

cache = Path("data/cache")
dfs = {}
for sym in ["159915", "510500", "510300"]:
    dfs[sym] = pd.read_pickle(cache / f"etf_{sym}.pkl")

common = sorted(
    set(pd.to_datetime(dfs["159915"]["date"]).dt.date) &
    set(pd.to_datetime(dfs["510500"]["date"]).dt.date) &
    set(pd.to_datetime(dfs["510300"]["date"]).dt.date)
)

aligned = {}
for sym, df in dfs.items():
    df2 = df.copy()
    df2["d"] = pd.to_datetime(df2["date"]).dt.date
    aligned[sym] = df2[df2["d"].isin(common)].set_index("d").sort_index()

# 分段
bull_start = pd.Timestamp("2024-01-01").date()
bear_dates = [d for d in common if d < bull_start]
bull_dates = [d for d in common if d >= bull_start]

print(f"熊市: {bear_dates[0]}~{bear_dates[-1]} ({len(bear_dates)}天)")
print(f"牛市: {bull_dates[0]}~{bull_dates[-1]} ({len(bull_dates)}天)")

print("\n=== 分段BH收益 ===")
for sym, df in aligned.items():
    def stats(dates):
        dp = df.loc[[d for d in dates if d in df.index]]
        c = dp["close"]
        total = c.iloc[-1] / c.iloc[0] - 1
        years = max((dates[-1] - dates[0]).days / 365.25, 0.01)
        ann = (1 + total) ** (1 / years) - 1
        return ann, total

    ann_bear, tot_bear = stats(bear_dates)
    ann_bull, tot_bull = stats(bull_dates)
    ann_all, tot_all = stats(common)
    print(f"{sym}: 全部{ann_all*100:.1f}%({tot_all*100:.1f}%) | 熊市{ann_bear*100:.1f}%({tot_bear*100:.1f}%) | 牛市{ann_bull*100:.1f}%({tot_bull*100:.1f}%)")

# 修复轮动策略bug
print("\n=== 三ETF轮动（修复版）===")
from strategies.rotation_strategy import RotationStrategy

dfs_rot = {}
for sym in aligned:
    df2 = aligned[sym].reset_index()  # d becomes a column
    # 现在同时有 date(原始列) 和 d(index转的列)，rename前先删date
    df2 = df2.drop(columns=["date"]).rename(columns={"d": "date"})
    dfs_rot[sym] = df2
strat = RotationStrategy(lookback_momentum=10, rebalance_freq=5)
rot = strat.generate(dfs_rot)

all_dates = pd.to_datetime(common).tolist()
capital = 100000.0
equity = [100000.0]

for i in range(1, len(all_dates)):
    d = all_dates[i]
    prev_d = all_dates[i - 1]

    # 找当天持仓ETF
    holder = None
    for sym, res in rot.items():
        dates_res = pd.to_datetime(res["date"]).values
        if d in dates_res:
            mask = dates_res == d
            pos_vals = res["position"].values
            if pos_vals[mask][0] == 1:
                holder = sym
                break

    if holder:
        res = rot[holder]
        dates_res = pd.to_datetime(res["date"]).values
        curr_idx = int(np.where(dates_res == d)[0][0])
        prev_idx = max(0, curr_idx - 1)
        ret = res["close"].iloc[curr_idx] / res["close"].iloc[prev_idx]
        capital *= ret

    equity.append(capital)

total = equity[-1] / 100000 - 1
years = (common[-1] - common[0]).days / 365.25
ann = (1 + total) ** (1 / years) - 1

# BH等权
bh_capital = 100000.0
bh_equity = [100000.0]
for i in range(1, len(all_dates)):
    avg = 0
    for sym, df in aligned.items():
        c = df["close"].values
        avg += (c[i] / c[i - 1] - 1) / 3
    bh_capital *= (1 + avg)
    bh_equity.append(bh_capital)

bh_total = bh_equity[-1] / 100000 - 1
bh_ann = (1 + bh_total) ** (1 / years) - 1

print(f"轮动: 年化{ann*100:.1f}%({total*100:.1f}%) vs BH等权{bh_ann*100:.1f}%({bh_total*100:.1f}%), 超额{ann-bh_ann:.1%}")
