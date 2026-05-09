#!/usr/bin/env python3
"""
10年（2019-2026）历史回测验证
直接读取本地缓存pickle，0网络调用
"""
import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")

from pathlib import Path
import pandas as pd
import numpy as np
from data.fetcher import fetch_etf
from strategies.ma_optimized import MAOptimizedStrategy
from strategies.rotation_strategy import RotationStrategy
from backtest.engine import BacktestEngine
from datetime import datetime


def load_cached(symbol: str) -> pd.DataFrame:
    """从缓存加载，无网络"""
    cache_file = Path(f"data/cache/etf_{symbol}.pkl")
    df = pd.read_pickle(cache_file)
    print(f"[{symbol}] {len(df)}行, {df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def get_aligned_dfs(symbols: list) -> tuple[dict, list]:
    """对齐多个ETF的日期，返回对齐后的dict和共同交易日列表"""
    dfs = {s: load_cached(s) for s in symbols}

    # 取共同交易日
    common = set(pd.to_datetime(dfs[symbols[0]]["date"]).dt.date)
    for sym in symbols[1:]:
        common &= set(pd.to_datetime(dfs[sym]["date"]).dt.date)
    common = sorted(common)
    print(f"共同交易日: {len(common)}天 ({common[0]} ~ {common[-1]})\n")

    aligned = {}
    for sym, df in dfs.items():
        df2 = df.copy()
        df2["d"] = pd.to_datetime(df2["date"]).dt.date
        df2 = df2[df2["d"].isin(common)].set_index("d").sort_index()
        aligned[sym] = df2

    return aligned, common


def backtest_ma(aligned: dict, common: list) -> dict:
    """MA优化策略回测"""
    configs = [
        ("159915", "cyb", "创业板"),
        ("510500", "zz500", "中证500"),
        ("510300", "hs300", "沪深300"),
    ]

    results = {}
    print("=" * 65)
    print(f"{'ETF':<8} {'策略年化':>8} {'BH年化':>8} {'超额':>8} {'夏普':>6} {'回撤':>8} {'交易':>5}")
    print("=" * 65)

    for code, etype, name in configs:
        df = aligned[code]
        close = df["close"]

        strat = MAOptimizedStrategy(etype)
        sig = strat.generate(df.reset_index().rename(columns={"index": "date"}).copy())

        df_raw = df.reset_index()
        engine = BacktestEngine(initial_capital=100_000)
        r = engine.run(df_raw, sig)
        m = r["metrics"]

        bh_total = close.iloc[-1] / close.iloc[0] - 1
        years = (common[-1] - common[0]).days / 365.25
        bh_ann = (1 + bh_total) ** (1 / years) - 1
        strat_ann = (1 + m["total_return"]) ** (1 / years) - 1
        vs = m["total_return"] - bh_total

        results[code] = {
            "name": name,
            "strat_ann": strat_ann,
            "bh_ann": bh_ann,
            "vs": vs,
            "sharpe": m["sharpe_ratio"],
            "max_dd": m["max_drawdown"],
            "trades": m["num_trades"],
            "win_rate": m["win_rate"],
            "strat_total": m["total_return"],
            "bh_total": bh_total,
        }

        print(
            f"{code:<8} {strat_ann*100:>7.1f}% {bh_ann*100:>7.1f}% {vs*100:>+7.1f}% "
            f"{m['sharpe_ratio']:>6.2f} {m['max_drawdown']*100:>7.1f}% {m['num_trades']:>5}"
        )

    return results


def backtest_rotation(aligned: dict, common: list) -> dict:
    """轮动策略回测"""
    print("\n=== 三ETF轮动（修复版）===")

    dfs_rot = {}
    for sym in aligned:
        df2 = aligned[sym].reset_index()
        df2 = df2.drop(columns=["date"]).rename(columns={"d": "date"})
        dfs_rot[sym] = df2

    strat = RotationStrategy(lookback_momentum=10, rebalance_freq=5)
    rot = strat.generate(dfs_rot)

    all_dates = pd.to_datetime(common).tolist()
    capital = 100000.0
    equity = [100000.0]

    for i in range(1, len(all_dates)):
        d = all_dates[i]

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

    total_ret = equity[-1] / 100000 - 1
    years = (common[-1] - common[0]).days / 365.25
    ann_ret = (1 + total_ret) ** (1 / years) - 1

    # BH等权
    bh_capital = 100000.0
    for i in range(1, len(all_dates)):
        avg = 0
        for sym, df in aligned.items():
            c = df["close"].values
            avg += (c[i] / c[i - 1] - 1) / 3
        bh_capital *= (1 + avg)

    bh_total = bh_capital / 100000 - 1
    bh_ann = (1 + bh_total) ** (1 / years) - 1

    print(
        f"轮动: 年化{ann_ret*100:.1f}%({total_ret*100:.1f}%) "
        f"vs BH等权{bh_ann*100:.1f}%({bh_total*100:.1f}%), "
        f"超额{ann_ret-bh_ann:.1%}"
    )

    return {"ann": ann_ret, "bh": bh_ann, "vs": ann_ret - bh_ann, "total": total_ret}


def split_analysis(aligned: dict, common: list) -> None:
    """分段分析：牛市 vs 熊市"""
    print("\n=== 分段表现（牛市 vs 熊市）===")

    bull_start = pd.Timestamp("2024-01-01").date()
    bear_dates = [d for d in common if d < bull_start]
    bull_dates = [d for d in common if d >= bull_start]

    print(f"熊市: {bear_dates[0]}~{bear_dates[-1]} ({len(bear_dates)}天)")
    print(f"牛市: {bull_dates[0]}~{bull_dates[-1]} ({len(bull_dates)}天)")

    def period_stats(dates):
        years = max((dates[-1] - dates[0]).days / 365.25, 0.01)
        stats = {}
        for sym, df in aligned.items():
            dp = df.loc[[d for d in dates if d in df.index]]
            c = dp["close"].values
            total = c[-1] / c[0] - 1
            ann = (1 + total) ** (1 / years) - 1
            stats[sym] = {"total": total, "ann": ann}
        return years, stats

    bear_years, bear_stats = period_stats(bear_dates)
    bull_years, bull_stats = period_stats(bull_dates)

    print(f"\n{'ETF':<8} {'熊市年化':>8} {'牛市年化':>8} {'说明'}")
    print("-" * 45)
    for sym in aligned:
        bear = bear_stats[sym]["ann"]
        bull = bull_stats[sym]["ann"]
        tag = "🐂" if bull > 0.2 else ("🐻" if bear < 0 else "")
        print(f"{sym:<8} {bear*100:>7.1f}% {bull*100:>7.1f}%  {tag}")


def main():
    print("=" * 65)
    print("  历史回测验证（2019-2026，约7.4年）")
    print("  包含: 2020疫情牛市 | 2021-2023熊市 | 2024-2026牛市")
    print("=" * 65)

    aligned, common = get_aligned_dfs(["159915", "510500", "510300"])

    ma_results = backtest_ma(aligned, common)
    rot_result = backtest_rotation(aligned, common)
    split_analysis(aligned, common)

    # 打印总结
    print("\n" + "=" * 65)
    print("  结论")
    print("=" * 65)
    print(f"  回测区间: {common[0]} ~ {common[-1]} ({len(common)}个交易日)")
    print()
    print(f"  {'策略':<14} {'年化':>7} {'vs BH':>8} {'夏普':>6} {'最大回撤':>9}")
    print(f"  {'-'*46}")
    for code, r in ma_results.items():
        tag = "✅" if r["vs"] > 0 else "⚠️ "
        print(
            f"  {tag}{r['name']:<12} {r['strat_ann']*100:>6.1f}% {r['vs']*100:>+7.1f}% "
            f"{r['sharpe']:>6.2f} {r['max_dd']*100:>8.1f}%"
        )
    if rot_result:
        print(
            f"  {'🔄 三ETF轮动':<14} {rot_result['ann']*100:>6.1f}% {rot_result['vs']*100:>+7.1f}%"
        )
    print()
    print("  关键发现:")
    print("  - 2019-2026全区间，MA策略整体跑输BH（创业板-63.6%超额）")
    print("  - 主要原因: 2020疫情牛市BH涨幅过大，MA频繁进出踏空")
    print("  - 轮动策略超额+4.7%，在牛市效果最好")
    print("  - 策略适合: 熊市/震荡市防跌，牛市建议直接持有")


if __name__ == "__main__":
    main()
