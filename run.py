#!/usr/bin/env python3
"""
量化交易系统 - 主运行脚本 v2

用法:
  python run.py --compare              # 多策略对比（2023-2024）
  python run.py --etf                 # ETF回测
  python run.py --all                 # 完整5年回测
  python run.py --wf                  # Walk-forward验证
  python run.py --strategy MA_Cross --symbol 510300 --bt   # 单策略回测
  python run.py --strategy MA_Cross --symbol 510300 --risk  # 带风控回测
  python run.py --multifactor         # 多因子策略回测
  python run.py --rotation            # 股债轮动策略
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from data.fetcher import fetch_stock, fetch_etf, fetch_index
from strategies.trend import MA_Cross, MACD_Strat, Breakout_20
from strategies.mean_reversion import RSI_Strat, BollingerBand, KD_Strat
from strategies.multi_factor import TripleFactorStrategy, MomentumFactorStrategy, quick_backtest
from strategies.stock_bond_rotation import StockBondRotationStrategy, load_tnx
from backtest.engine import BacktestEngine
from backtest.risk import BacktestEngineV2, PositionConfig


STOCKS = ["000001", "000002", "600519", "600036", "000858"]
ETFS = {
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "159915": "创业板ETF",
    "512100": "纳指ETF",
}


def run_etf_backtest(start="20230101", end="20241231", with_risk=False):
    """ETF回测 - 多策略对比"""
    print(f"\n{'='*65}")
    print(f"  ETF 回测 ({start} ~ {end})")
    print(f"{'='*65}")

    strats = [
        MA_Cross(5, 20),
        MA_Cross(10, 60),
        MA_Cross(20, 120),
        MACD_Strat(),
        Breakout_20(20),
        Breakout_20(50),
        RSI_Strat(14),
        BollingerBand(20, 2.0),
    ]

    for etf, etf_name in ETFS.items():
        df = fetch_etf(etf, start, end)
        if len(df) < 50:
            print(f"\n  {etf_name}({etf}): 数据不足")
            continue

        buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
        print(f"\n  {etf_name}({etf}) - 买入持有: {buyhold*100:.2f}%")
        print(f"  {'策略':<18} {'总收益':>8} {'年化':>8} {'最大回撤':>10} {'夏普':>8} {'交易':>6}")
        print(f"  {'-'*60}")

        for strat in strats:
            signals = strat.generate(df)
            if with_risk:
                cfg = PositionConfig(
                    base_ratio=0.8,
                    stop_loss=0.07,
                    trailing_stop=True,
                    trailing_pct=0.05,
                    take_profit=0,
                )
                engine = BacktestEngineV2(initial_capital=100_000, risk_config=cfg)
                tag = "[风控]"
            else:
                engine = BacktestEngine(initial_capital=100_000)
                tag = ""

            result = engine.run(df, signals)
            m = result["metrics"]

            print(f"  {strat.name:<18} {m['total_return']*100:>7.2f}% "
                  f"{m['annual_return']*100:>7.2f}% {m['max_drawdown']*100:>9.2f}% "
                  f"{m['sharpe_ratio']:>7.2f} {m['num_trades']:>5}")


def run_full_backtest():
    """完整5年回测"""
    print(f"\n{'='*65}")
    print(f"  完整5年回测 (2019-01-01 ~ 2024-12-31)")
    print(f"{'='*65}")

    for etf, etf_name in ETFS.items():
        df = fetch_etf(etf, "20190101", "20241231")
        if len(df) < 200:
            continue

        buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
        print(f"\n  {etf_name}({etf}) - 买入持有: {buyhold*100:.2f}%")

        strats = [MA_Cross(10, 60), MACD_Strat(), Breakout_20(20)]
        for strat in strats:
            signals = strat.generate(df)
            result = BacktestEngine(initial_capital=100_000).run(df, signals)
            m = result["metrics"]
            print(f"  {strat.name:<15}: 收益={m['total_return']*100:>6.2f}% "
                  f"年化={m['annual_return']*100:>6.2f}% 回撤={m['max_drawdown']*100:>7.2f}% "
                  f"夏普={m['sharpe_ratio']:>5.2f} 交易={m['num_trades']}")


def run_single_backtest(strategy_name: str, symbol: str, with_risk: bool = False):
    """运行单个回测"""
    df = fetch_etf(symbol, "20230101", "20241231")
    print(f"\n数据: {symbol}, {len(df)}条, {df['date'].min().date()} ~ {df['date'].max().date()}")

    strat_map = {
        "MA_Cross": MA_Cross(5, 20),
        "MA_Cross_10_60": MA_Cross(10, 60),
        "MACD": MACD_Strat(),
        "Breakout": Breakout_20(),
        "RSI": RSI_Strat(),
        "BB": BollingerBand(),
        "KD": KD_Strat(),
    }

    strat = strat_map.get(strategy_name)
    if not strat:
        print(f"未知策略: {strategy_name}")
        return

    print(f"策略: {strat.name}")
    signals = strat.generate(df)

    if with_risk:
        cfg = PositionConfig(
            base_ratio=0.8,
            stop_loss=0.07,
            trailing_stop=True,
            trailing_pct=0.05,
        )
        engine = BacktestEngineV2(initial_capital=100_000, risk_config=cfg)
    else:
        engine = BacktestEngine(initial_capital=100_000)

    result = engine.run(df, signals)
    engine.print_report(result, strat.name)
    return result


def run_strategy_comparison():
    """多策略对比"""
    print("\n" + "=" * 60)
    print("  多策略对比 (2023-2024)")
    print("=" * 60)

    strats = [
        MA_Cross(5, 20),
        MA_Cross(10, 60),
        MACD_Strat(),
        Breakout_20(20),
        RSI_Strat(14),
        BollingerBand(20, 2.0),
    ]

    results = []
    for etf in ["510300", "510500", "159915"]:
        df = fetch_etf(etf, "20230101", "20241231")
        if len(df) < 100:
            continue

        for strat in strats:
            try:
                signals = strat.generate(df)
                m = BacktestEngine(initial_capital=100_000).run(df, signals)["metrics"]
                results.append({**m, "strategy": strat.name, "symbol": etf})
            except Exception as e:
                print(f"  {etf}/{strat.name}: 错误 - {e}")

    # 汇总排序
    print(f"\n{'策略':<18} {'ETF':<8} {'年化':>8} {'最大回撤':>10} {'夏普':>8}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: x["sharpe_ratio"], reverse=True):
        print(f"  {r['strategy']:<18} {r['symbol']:<8} "
              f"{r['annual_return']*100:>7.2f}% {r['max_drawdown']*100:>9.2f}% {r['sharpe_ratio']:>7.2f}")


def run_multifactor_backtest(start="20230101", end="20241231"):
    """多因子策略回测"""
    print("\n" + "=" * 65)
    print(f"  多因子策略回测 ({start} ~ {end})")
    print("=" * 65)

    for etf, etf_name in ETFS.items():
        df = fetch_etf(etf, start, end)
        if len(df) < 100:
            continue

        buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
        print(f"\n  {etf_name}({etf}) - 买入持有: {buyhold*100:.2f}%")

        # 1. 动量因子策略（纯技术）
        mom_strat = MomentumFactorStrategy()
        mom_signals = mom_strat.generate(df)
        mom_result = quick_backtest(df, mom_signals)

        # 2. 三因子策略（技术+基本面，无情感数据）
        try:
            from data.fundamental import fetch_etf_fundamental
            fund_df = fetch_etf_fundamental(etf, start, end)
            triple_strat = TripleFactorStrategy(
                tech_weight=0.60,
                fund_weight=0.30,
                sent_weight=0.10,
            )
            triple_signals = triple_strat.generate(df, fund_data=fund_df)
            triple_result = quick_backtest(df, triple_signals)
        except Exception as e:
            print(f"    基本面数据加载失败: {e}")
            triple_result = None

        # 对比表格
        print(f"  {'策略':<22} {'总收益':>8} {'夏普':>7} {'最大回撤':>9} {'交易数':>7}")
        print(f"  {'-'*60}")
        print(f"  {'动量因子(MomentumFactor)':<22} {mom_result['total_return']:>7.2f}% "
              f"{mom_result['sharpe']:>7.2f} {mom_result['max_drawdown']:>8.2f}% "
              f"{mom_result['n_trades']:>6}")
        if triple_result:
            print(f"  {'三因子(TripleFactor)':<22} {triple_result['total_return']:>7.2f}% "
                  f"{triple_result['sharpe']:>7.2f} {triple_result['max_drawdown']:>8.2f}% "
                  f"{triple_result['n_trades']:>6}")

        # 与买入持有对比
        print(f"  {'买入持有':<22} {buyhold*100:>7.2f}% {'基准':>7} {'--':>9} {'--':>6}")


def run_rotation_backtest(start="20230101", end="20241231"):
    """股债轮动策略回测"""
    print("\n" + "=" * 65)
    print(f"  股债轮动策略 ({start} ~ {end})")
    print("=" * 65)

    # 加载国债收益率
    tnx = load_tnx()
    if tnx.empty:
        print("  ⚠️ 国债收益率数据为空，跳过轮动策略")
        return

    for etf, etf_name in ETFS.items():
        df = fetch_etf(etf, start, end)
        if len(df) < 100:
            continue

        buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
        print(f"\n  {etf_name}({etf}) - 买入持有: {buyhold*100:.2f}%")

        # 轮动策略
        strat = StockBondRotationStrategy(mode="trend_spread", rebalance_days=10)
        signals = strat.generate(df, bond_data=tnx)
        if signals.empty:
            print(f"    无信号数据")
            continue

        result = quick_backtest(df, signals)

        print(f"  {'轮动(Trend+Spread)':<22} {result['total_return']:>7.2f}% "
              f"{result['sharpe']:>7.2f} {result['max_drawdown']:>8.2f}% "
              f"{result['n_trades']:>6}")

        # 纯利差模式
        strat2 = StockBondRotationStrategy(mode="spread", rebalance_days=10)
        sig2 = strat2.generate(df, bond_data=tnx)
        r2 = quick_backtest(df, sig2)
        print(f"  {'轮动(Spread Only)':<22} {r2['total_return']:>7.2f}% "
              f"{r2['sharpe']:>7.2f} {r2['max_drawdown']:>8.2f}% "
              f"{r2['n_trades']:>6}")


def main():
    parser = argparse.ArgumentParser(description="量化交易系统 v2")
    parser.add_argument("--strategy", default="all", help="策略名")
    parser.add_argument("--symbol", default="510300", help="代码")
    parser.add_argument("--bt", action="store_true", help="运行回测")
    parser.add_argument("--risk", action="store_true", help="带风控")
    parser.add_argument("--compare", action="store_true", help="多策略对比")
    parser.add_argument("--etf", action="store_true", help="ETF回测")
    parser.add_argument("--all", action="store_true", help="完整5年回测")
    parser.add_argument("--wf", action="store_true", help="Walk-forward分析")
    parser.add_argument("--multifactor", action="store_true", help="多因子策略")
    parser.add_argument("--rotation", action="store_true", help="股债轮动策略")
    parser.add_argument("--start", default="20230101", help="开始日期")
    parser.add_argument("--end", default="20241231", help="结束日期")

    args = parser.parse_args()

    if args.wf:
        from scripts.walk_forward import main as wf_main
        wf_main()
    elif args.all:
        run_full_backtest()
    elif args.multifactor:
        run_multifactor_backtest(args.start, args.end)
    elif args.rotation:
        run_rotation_backtest(args.start, args.end)
    elif args.etf:
        run_etf_backtest(args.start, args.end, args.risk)
    elif args.compare:
        run_strategy_comparison()
    elif args.bt or args.strategy != "all":
        run_single_backtest(args.strategy, args.symbol, args.risk)
    else:
        print("默认运行: ETF多策略对比")
        run_etf_backtest(args.start, args.end)


if __name__ == "__main__":
    main()
