#!/usr/bin/env python3
"""
Walk-Forward 验证脚本
训练252天(1年) / 测试63天(1季度) 滚动窗口
"""

import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")

from backtest.engine import BacktestEngine
from data.fetcher import fetch_etf
from data.fundamental import fetch_etf_fundamental
from strategies.trend import MA_Cross, MACD_Strat, Breakout_20
from strategies.mean_reversion import RSI_Strat
from strategies.multi_factor import TripleFactorStrategy, MomentumFactorStrategy
from strategies.stock_bond_rotation import StockBondRotationStrategy, load_tnx


def walk_forward_validate(symbol, strat_cls, params, train_days=252, test_days=63):
    df = fetch_etf(symbol, "20190101", "20241231")

    # 基本面数据（如策略需要）
    fund_df = None
    try:
        fund_df = fetch_etf_fundamental(symbol, "20190101", "20241231")
    except:
        pass

    # TNX（如策略需要）
    tnx = load_tnx()

    # 根据策略类型生成信号
    if strat_cls == TripleFactorStrategy:
        signals = strat_cls(*params).generate(df, fund_data=fund_df)
    elif strat_cls == MomentumFactorStrategy:
        signals = strat_cls(*params).generate(df)
    elif strat_cls == StockBondRotationStrategy:
        signals = strat_cls(*params).generate(df, bond_data=tnx)
    else:
        signals = strat_cls(*params).generate(df)

    # 确保信号有date列
    if "date" not in signals.columns:
        signals = signals.reset_index().rename(columns={"index": "date"})
    sig_dates = signals["date"].values

    n = len(df)
    df_dates = df["date"].values
    results = []

    for start in range(0, n - test_days, test_days):
        train_end = start + train_days
        test_end = min(start + train_days + test_days, n)

        if train_end > n:
            break

        # 用日期切片，不用iloc（策略信号可能不对齐索引）
        train_dates_set = set(df_dates[start:train_end])
        test_dates_set = set(df_dates[train_end:test_end])

        test_df = df[df["date"].isin(test_dates_set)].copy()
        test_sig = signals[signals["date"].isin(test_dates_set)].copy()

        # 清理信号：移除NaN，填充0
        if "signal" in test_sig.columns:
            test_sig["signal"] = test_sig["signal"].fillna(0).replace({-0: 0})
        if "position" in test_sig.columns:
            test_sig["position"] = test_sig["position"].fillna(0)

        if len(test_df) < 20 or len(test_sig) == 0:
            continue

        # 日期排序对齐
        test_df = test_df.sort_values("date").reset_index(drop=True)
        test_sig = test_sig.sort_values("date").reset_index(drop=True)

        engine = BacktestEngine(initial_capital=100_000)
        try:
            r = engine.run(test_df, test_sig)
            m = r["metrics"]
        except Exception as e:
            # 回退到quick_backtest（更robust）
            from strategies.multi_factor import quick_backtest
            test_sig_clean = test_sig.copy()
            if "signal" in test_sig_clean.columns:
                test_sig_clean["signal"] = test_sig_clean["signal"].fillna(0).astype(int)
            if "position" in test_sig_clean.columns:
                test_sig_clean["position"] = test_sig_clean["position"].fillna(0)
            try:
                r2 = quick_backtest(test_df, test_sig_clean)
                m = {
                    "annual_return": r2["total_return"] / 100,
                    "sharpe_ratio": r2["sharpe"],
                    "max_drawdown": r2["max_drawdown"] / 100,
                    "num_trades": r2["n_trades"],
                }
            except Exception as e2:
                print(f"      [警告] quick_backtest也失败: {e2}")
                continue

        # 基准
        bh = (test_df["close"].iloc[-1] / test_df["close"].iloc[0]) - 1
        bh_ann = (1 + bh) ** (252 / len(test_df)) - 1

        results.append({
            "period": f"{test_df.iloc[0]['date'].strftime('%Y-%m')}~{test_df.iloc[-1]['date'].strftime('%Y-%m')}",
            "ann_ret": m["annual_return"] * 100,
            "sharpe": m["sharpe_ratio"],
            "max_dd": m["max_drawdown"] * 100,
            "excess": (m["annual_return"] - bh_ann) * 100,
            "trades": m["num_trades"],
            "bench": bh * 100,
        })

    return results


def main():
    print("=" * 75)
    print("  Walk-Forward 验证 (训练252天 / 测试63天)")
    print("=" * 75)

    strats = [
        ("MA(5,20)", MA_Cross, (5, 20)),
        ("MA(10,60)", MA_Cross, (10, 60)),
        ("MACD", MACD_Strat, ()),
        ("Breakout(20)", Breakout_20, (20,)),
        ("RSI(14)", RSI_Strat, (14,)),
        ("TripleFactor", TripleFactorStrategy, ()),
        ("MomentumFactor", MomentumFactorStrategy, ()),
        ("TrendSpread", StockBondRotationStrategy, ("trend_spread", 10)),
    ]

    etfs = [
        ("510300", "沪深300ETF"),
        ("510500", "中证500ETF"),
        ("159915", "创业板ETF"),
    ]

    all_results = {}

    for etf, etf_name in etfs:
        print(f"\n>>> {etf_name}({etf})")
        print("-" * 70)

        for name, cls, params in strats:
            results = walk_forward_validate(etf, cls, params)
            if not results:
                continue

            ann_rets = [r["ann_ret"] for r in results]
            sharpes = [r["sharpe"] for r in results]
            excess_rets = [r["excess"] for r in results]

            win_rate = len([r for r in results if r["ann_ret"] > 0]) / len(results) * 100
            beat_bench = len([r for r in results if r["excess"] > 0]) / len(results) * 100

            key = f"{name}_{etf}"
            all_results[key] = {
                "etf": etf_name,
                "strategy": name,
                "periods": len(results),
                "win_rate": win_rate,
                "beat_bench": beat_bench,
                "avg_ann": sum(ann_rets) / len(ann_rets),
                "avg_sharpe": sum(sharpes) / len(sharpes),
                "avg_excess": sum(excess_rets) / len(excess_rets),
            }

            print(f"  {name:15s}: 周期={len(results):2d} | "
                  f"跑赢基准={beat_bench:4.0f}% | "
                  f"正收益={win_rate:4.0f}% | "
                  f"平均年化={sum(ann_rets)/len(ann_rets):6.1f}% | "
                  f"平均夏普={sum(sharpes)/len(sharpes):5.2f}")

    # 汇总：各ETF最佳策略
    print("\n" + "=" * 75)
    print("  汇总：各ETF最佳策略")
    print("=" * 75)
    for etf, etf_name in etfs:
        etf_results = [(k, v) for k, v in all_results.items() if f"_{etf}" in k]
        if not etf_results:
            continue
        best = max(etf_results, key=lambda x: x[1]["avg_sharpe"])
        print(f"  {etf_name}({etf}): 最佳={best[0]}, 夏普={best[1]['avg_sharpe']:.2f}, "
              f"跑赢基准={best[1]['beat_bench']:.0f}%")


if __name__ == "__main__":
    main()
