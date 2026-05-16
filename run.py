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
from strategies.ensemble import (
    EnsembleStrategy, AdaptiveEnsemble, VotingEnsemble, RegimeSwitchingEnsemble
)
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


def run_ensemble_backtest(start="20230101", end="20241231"):
    """集成策略回测"""
    print("\n" + "=" * 65)
    print(f"  集成策略回测 ({start} ~ {end})")
    print("=" * 65)

    from strategies.multi_factor import quick_backtest

    strats = {
        "Ensemble(等权)": EnsembleStrategy(),
        "AdaptiveEnsemble(自适应)": AdaptiveEnsemble(),
        "VotingEnsemble(投票)": VotingEnsemble(),
        "RegimeSwitching(状态切换)": RegimeSwitchingEnsemble(),
    }

    for etf, etf_name in ETFS.items():
        df = fetch_etf(etf, start, end)
        if len(df) < 50:
            continue

        buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
        print(f"\n  {etf_name}({etf}) - 买入持有: {buyhold*100:.2f}%")
        print(f"  {'策略':<25} {'总收益':>8} {'夏普':>7} {'交易':>6}")
        print(f"  {'-'*55}")

        for name, strat in strats.items():
            try:
                sig = strat.generate(df)
                res = quick_backtest(df, sig)
                print(f"  {name:<25} {res['total_return']:>7.2f}% "
                      f"{res['sharpe']:>7.2f} {res['n_trades']:>5}")
            except Exception as e:
                print(f"  {name:<25} ERROR: {str(e)[:30]}")


def run_long_alpha_backtest(start: str = "20230101", end: str = "20241231",
                            symbol: str = "510300") -> None:
    """长线价值 Alpha 策略回测。"""
    from strategies.value_long import ValueLongStrategy

    print(f"\n{'='*65}")
    print(f"  长线价值 Alpha 策略 ({start} ~ {end})")
    print(f"{'='*65}")

    df = fetch_etf(symbol, start, end)
    if len(df) < 50:
        print(f"  {symbol}: 数据不足（{len(df)}条）")
        return

    strat = ValueLongStrategy(symbol=symbol)
    signals = strat.generate(df)
    result = BacktestEngine(initial_capital=100_000).run(df, signals)
    m = result["metrics"]

    buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
    print(f"  标的: {symbol}  数据: {len(df)}条")
    print(f"  {'指标':<14} {'策略':>10} {'买入持有':>10}")
    print(f"  {'-'*38}")
    print(f"  {'总收益':<14} {m['total_return']*100:>9.2f}% {buyhold*100:>9.2f}%")
    print(f"  {'年化收益':<14} {m['annual_return']*100:>9.2f}%")
    print(f"  {'最大回撤':<14} {m['max_drawdown']*100:>9.2f}%")
    print(f"  {'夏普比率':<14} {m['sharpe_ratio']:>10.2f}")
    print(f"  {'交易次数':<14} {m['num_trades']:>10}")
    composite = signals["composite_score"].iloc[0]
    print(f"  {'复合因子分':<14} {composite:>10.3f}")


def run_event_driven_backtest(start: str = "20230101", end: str = "20241231",
                              symbol: str = "510300") -> None:
    """事件驱动策略回测。"""
    from strategies.event_driven import EventDrivenStrategy

    print(f"\n{'='*65}")
    print(f"  事件驱动策略 ({start} ~ {end})")
    print(f"{'='*65}")

    df = fetch_etf(symbol, start, end)
    if len(df) < 50:
        print(f"  {symbol}: 数据不足（{len(df)}条）")
        return

    strat = EventDrivenStrategy(symbol=symbol)
    signals = strat.generate(df)
    result = BacktestEngine(initial_capital=100_000).run(df, signals)
    m = result["metrics"]

    buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
    print(f"  标的: {symbol}  数据: {len(df)}条")
    print(f"  {'指标':<14} {'策略':>10} {'买入持有':>10}")
    print(f"  {'-'*38}")
    print(f"  {'总收益':<14} {m['total_return']*100:>9.2f}% {buyhold*100:>9.2f}%")
    print(f"  {'年化收益':<14} {m['annual_return']*100:>9.2f}%")
    print(f"  {'最大回撤':<14} {m['max_drawdown']*100:>9.2f}%")
    print(f"  {'夏普比率':<14} {m['sharpe_ratio']:>10.2f}")
    print(f"  {'交易次数':<14} {m['num_trades']:>10}")


def run_regime_portfolio_backtest(start: str = "20230101", end: str = "20241231",
                                  symbol: str = "510300") -> None:
    """Regime 调度组合回测（长线 Alpha + 事件驱动 + MVO + Regime）。"""
    import numpy as np
    from strategies.value_long import ValueLongStrategy
    from strategies.event_driven import EventDrivenStrategy
    from portfolio.optimizer import MVOptimizer
    from portfolio.regime_gating import RegimeDetector

    print(f"\n{'='*65}")
    print(f"  Regime 组合策略 ({start} ~ {end})")
    print(f"{'='*65}")

    df = fetch_etf(symbol, start, end)
    if len(df) < 50:
        print(f"  {symbol}: 数据不足（{len(df)}条）")
        return

    # 生成两策略信号
    va_signals = ValueLongStrategy(symbol=symbol).generate(df)
    ev_signals = EventDrivenStrategy(symbol=symbol).generate(df)

    # Regime 检测
    detector = RegimeDetector()
    regime = detector.detect(df["close"], avg_sentiment=0.0)
    weights = detector.get_weights(regime)

    # 合成仓位（加权平均取整）
    w_va = weights["long_alpha"]
    w_ev = weights["event_driven"]
    combined_pos = (va_signals["position"] * w_va + ev_signals["position"] * w_ev)
    combined_pos = (combined_pos >= 0.5).astype(int)
    combined_sig = combined_pos.diff().fillna(0).astype(int)

    signals = df.copy()
    signals["position"] = combined_pos.values
    signals["signal"] = combined_sig.values

    result = BacktestEngine(initial_capital=100_000).run(df, signals)
    m = result["metrics"]

    buyhold = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1
    print(f"  标的: {symbol}  Regime: {regime}")
    print(f"  长线 Alpha 权重: {w_va:.2f}  事件驱动权重: {w_ev:.2f}")
    print(f"  {'指标':<14} {'策略':>10} {'买入持有':>10}")
    print(f"  {'-'*38}")
    print(f"  {'总收益':<14} {m['total_return']*100:>9.2f}% {buyhold*100:>9.2f}%")
    print(f"  {'年化收益':<14} {m['annual_return']*100:>9.2f}%")
    print(f"  {'最大回撤':<14} {m['max_drawdown']*100:>9.2f}%")
    print(f"  {'夏普比率':<14} {m['sharpe_ratio']:>10.2f}")
    print(f"  {'交易次数':<14} {m['num_trades']:>10}")


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
    parser.add_argument("--ensemble", action="store_true", help="集成策略")
    parser.add_argument("--start", default="20230101", help="开始日期")
    parser.add_argument("--end", default="20241231", help="结束日期")
    parser.add_argument("--update-data", action="store_true", help="更新结构化数据存储")
    parser.add_argument("--update-knowledge", action="store_true", help="更新知识库卡片")
    parser.add_argument("--industry-map", default="", help="构建行业图谱（传行业名或all）")
    parser.add_argument("--train-ml", action="store_true", help="训练ML基线并评估")
    parser.add_argument("--ml-backtest", action="store_true", help="运行ML策略回测")
    parser.add_argument("--daily-pipeline", action="store_true", help="运行一站式每日流水线")
    parser.add_argument("--long-alpha", action="store_true", help="长线价值 Alpha 策略回测")
    parser.add_argument("--event-driven", action="store_true", help="事件驱动策略回测")
    parser.add_argument("--regime-portfolio", action="store_true", help="Regime 组合策略回测")

    args = parser.parse_args()

    if args.long_alpha:
        run_long_alpha_backtest(args.start, args.end, args.symbol)
    elif args.event_driven:
        run_event_driven_backtest(args.start, args.end, args.symbol)
    elif args.regime_portfolio:
        run_regime_portfolio_backtest(args.start, args.end, args.symbol)
    elif args.update_data:
        from scripts.update_data_store import run as update_data_store_run
        print(update_data_store_run())
    elif args.update_knowledge:
        from scripts.update_knowledge import run as update_knowledge_run
        print(update_knowledge_run())
    elif args.industry_map:
        from scripts.build_industry_graph import run as build_industry_graph_run
        print(build_industry_graph_run())
    elif args.train_ml:
        from scripts.train_ml_strategy import run as train_ml_run
        print(train_ml_run(symbol=args.symbol, start=args.start, end=args.end))
    elif args.ml_backtest:
        from scripts.run_ml_backtest import run as run_ml_backtest_run
        print(run_ml_backtest_run(symbol=args.symbol, start=args.start, end=args.end))
    elif args.daily_pipeline:
        from scripts.daily_pipeline import run_daily_pipeline
        print(run_daily_pipeline())
    elif args.wf:
        from scripts.walk_forward import main as wf_main
        wf_main()
    elif args.all:
        run_full_backtest()
    elif args.multifactor:
        run_multifactor_backtest(args.start, args.end)
    elif args.rotation:
        run_rotation_backtest(args.start, args.end)
    elif args.ensemble:
        run_ensemble_backtest(args.start, args.end)
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
