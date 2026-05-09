#!/usr/bin/env python3
"""快速策略对比"""
import sys
sys.path.insert(0, '/Users/tanwei/quant-trading')

from data.fetcher import fetch_etf
from strategies.multi_factor import TripleFactorStrategy, MomentumFactorStrategy, quick_backtest
from strategies.stock_bond_rotation import StockBondRotationStrategy
from strategies.trend import MA_Cross

ETFS = [("510300", "沪深300"), ("510500", "中证500"), ("159915", "创业板")]
strats = {
    "TripleFactor": TripleFactorStrategy(),
    "MomentumFactor": MomentumFactorStrategy(),
    "MA_Cross(5,20)": MA_Cross(5, 20),
    "StockBondRotation": StockBondRotationStrategy(),
}

print(f"\n{'='*70}")
print(f"  策略对比 (2023-01-01 ~ 2024-12-31)")
print(f"{'='*70}")

for etf, name in ETFS:
    df = fetch_etf(etf, "20230101", "20241231")
    bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    print(f"\n{name}({etf}) 买入持有: {bh*100:.2f}%")
    print(f"  {'策略':<20} {'收益':>8} {'夏普':>6} {'交易':>6} {'最大回撤':>10}")
    print(f"  {'-'*55}")
    for sname, strat in strats.items():
        sig = strat.generate(df)
        res = quick_backtest(df, sig)
        m = res
        print(f"  {sname:<20} {m['total_return']:>7.2f}% {m['sharpe']:>6.2f} {m['n_trades']:>5} {m['max_drawdown']:>9.2f}%")

print(f"\n{'='*70}")
