#!/usr/bin/env python3
"""
量化交易系统 - 主运行脚本
用法:
  python run.py                    # 运行所有策略对比
  python run.py --strategy MA_Cross --stock 000001 --bt  # 单策略回测
  python run.py --paper             # 模拟交易
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from data.fetcher import fetch_stock, fetch_etf, fetch_index
from strategies.trend import MA_Cross, MACD_Strat, Breakout_20
from strategies.mean_reversion import RSI_Strat, BollingerBand, KD_Strat
from backtest.engine import BacktestEngine


# ============================================================
# 预定义回测任务
# ============================================================

STOCKS = ["000001", "000002", "600519", "600036", "000858"]
ETFS = ["510300", "510500", "159915"]  # 沪深300、中证500、创业板


def run_strategy_comparison():
    """运行多策略对比"""
    print("\n" + "=" * 60)
    print("  量化交易系统 - 多策略对比")
    print("=" * 60)

    strategies = [
        MA_Cross(5, 20),
        MA_Cross(10, 60),
        MACD_Strat(12, 26, 9),
        Breakout_20(20),
        RSI_Strat(14),
        BollingerBand(20, 2.0),
    ]

    results_summary = []

    for strat in strategies:
        print(f"\n{'='*50}")
        print(f"  策略: {strat.name}")
        print(f"{'='*50}")

        for stock in STOCKS[:3]:  # 先跑3只
            try:
                data = fetch_stock(stock, "20230101", "20241231")
                if len(data) < 100:
                    continue

                signals = strat.generate(data)

                engine = BacktestEngine(
                    initial_capital=100_000,
                    commission=0.0003,
                    slippage=0.0001,
                )
                result = engine.run(data, signals)

                m = result["metrics"]
                print(
                    f"  {stock}: 收益={m['total_return']*100:>7.2f}% | "
                    f"年化={m['annual_return']*100:>7.2f}% | "
                    f"回撤={m['max_drawdown']*100:>7.2f}% | "
                    f"夏普={m['sharpe_ratio']:>6.2f} | "
                    f"交易={m['num_trades']:>3}"
                )

                results_summary.append({
                    "strategy": strat.name,
                    "stock": stock,
                    **m,
                })
            except Exception as e:
                print(f"  {stock}: 错误 - {e}")

    # 汇总
    print("\n" + "=" * 60)
    print("  汇总结果")
    print("=" * 60)
    print(f"  {'策略':<20} {'股票':<8} {'年化':>8} {'最大回撤':>10} {'夏普':>8} {'交易次数':>8}")
    print("-" * 60)
    for r in sorted(results_summary, key=lambda x: x["sharpe_ratio"], reverse=True):
        print(
            f"  {r['strategy']:<20} {r['stock']:<8} "
            f"{r['annual_return']*100:>7.2f}% "
            f"{r['max_drawdown']*100:>9.2f}% "
            f"{r['sharpe_ratio']:>7.2f} "
            f"{r['num_trades']:>8}"
        )


def run_single_backtest(strategy_name: str, stock: str):
    """运行单个回测"""
    data = fetch_stock(stock, "20230101", "20241231")
    print(f"\n数据: {stock}, {len(data)}条, {data['date'].min().date()} ~ {data['date'].max().date()}")

    # 选择策略
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
        print(f"可用策略: {list(strat_map.keys())}")
        return

    print(f"策略: {strat.name}")
    signals = strat.generate(data)

    engine = BacktestEngine(initial_capital=100_000)
    result = engine.run(data, signals)
    engine.print_report(result, strat.name)

    return result


def run_walk_forward(stock: str = "000001", strategy: str = "MA_Cross"):
    """Walk-forward分析"""
    print(f"\nWalk-forward分析: {stock} / {strategy}")

    data = fetch_stock(stock, "20200101", "20241231")
    print(f"数据: {len(data)} 条")

    strat = MA_Cross(5, 20)
    signals = strat.generate(data)

    engine = BacktestEngine(initial_capital=100_000)
    wf_results = engine.walk_forward(data, signals, train_window=252, test_window=63)

    print(f"\n{'='*50}")
    print(f"  Walk-Forward 结果")
    print(f"{'='*50}")
    print(f"  {'训练期':>20} {'测试期':>20} {'年化':>10} {'夏普':>8}")
    print("-" * 60)
    for r in wf_results:
        m = r["metrics"]
        print(
            f"  {r['train_start']:>4}-{r['train_end']:<4} "
            f"{r['test_start']:>4}-{r['test_end']:<4}  "
            f"{m['annual_return']*100:>9.2f}% "
            f"{m['sharpe_ratio']:>7.2f}"
        )

    # 平均表现
    avg_ann = sum(r['metrics']['annual_return'] for r in wf_results) / len(wf_results)
    avg_sharpe = sum(r['metrics']['sharpe_ratio'] for r in wf_results) / len(wf_results)
    print(f"\n  平均年化: {avg_ann*100:.2f}%")
    print(f"  平均夏普: {avg_sharpe:.2f}")


def run_etf_backtest():
    """ETF回测 - 更容易出趋势"""
    print("\n" + "=" * 55)
    print("  ETF 回测（趋势策略）")
    print("=" * 55)

    strat = MA_Cross(5, 20)
    results = []

    for etf in ETFS:
        try:
            data = fetch_etf(etf, "20200101", "20241231")
            if len(data) < 200:
                continue

            signals = strat.generate(data)
            engine = BacktestEngine(initial_capital=100_000)
            result = engine.run(data, signals)
            m = result["metrics"]

            # 买入持有
            buyhold = (data["close"].iloc[-1] / data["close"].iloc[0]) - 1

            print(
                f"\n  {etf}:"
            )
            print(f"    策略: 收益={m['total_return']*100:.2f}% 年化={m['annual_return']*100:.2f}% "
                  f"回撤={m['max_drawdown']*100:.2f}% 夏普={m['sharpe_ratio']:.2f}")
            print(f"    买入持有: {buyhold*100:.2f}%")

            results.append({**m, "symbol": etf, "buyhold": buyhold})
        except Exception as e:
            print(f"\n  {etf}: 错误 - {e}")

    return results


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="量化交易系统")
    parser.add_argument("--strategy", default="all", help="策略名")
    parser.add_argument("--stock", default="000001", help="股票代码")
    parser.add_argument("--bt", action="store_true", help="运行回测")
    parser.add_argument("--wf", action="store_true", help="Walk-forward分析")
    parser.add_argument("--etf", action="store_true", help="ETF回测")
    parser.add_argument("--compare", action="store_true", help="多策略对比")

    args = parser.parse_args()

    if args.wf:
        run_walk_forward(args.stock, args.strategy)
    elif args.etf:
        run_etf_backtest()
    elif args.compare:
        run_strategy_comparison()
    elif args.bt or args.strategy != "all":
        run_single_backtest(args.strategy, args.stock)
    else:
        # 默认：运行所有
        print("\n默认运行: 多策略对比 + ETF回测")
        run_strategy_comparison()
        run_etf_backtest()


if __name__ == "__main__":
    main()
