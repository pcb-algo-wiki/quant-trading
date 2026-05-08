"""
估值择时策略 - 真实数据回测
使用Yahoo Finance获取的真实数据
"""

import sys
sys.path.insert(0, '/Users/tanwei/quant-trading')

import pandas as pd
import numpy as np
from strategies.real_data_strategies import (
    EquityBondSpreadStrategy,
    TrendFollowingStrategy,
    DualMovingAverageStrategy,
    MomentumStrategy,
    CombinedStrategy,
    Backtester
)
import os, pickle

CACHE_DIR = '/Users/tanwei/quant-trading/data/cache'

def load_data():
    """加载缓存数据"""
    data = {}
    for name in ['510300', '510500', '159915']:
        path = f'{CACHE_DIR}/yahoo_{name}.pkl'
        if os.path.exists(path):
            df = pd.read_pickle(path)
            data[name] = df
    
    tnx_path = f'{CACHE_DIR}/yahoo_TNX.pkl'
    if os.path.exists(tnx_path):
        data['TNX'] = pd.read_pickle(tnx_path)
    
    return data

def run_all_strategies():
    print("=" * 70)
    print("真实数据策略回测")
    print("数据来源: Yahoo Finance (2021-2026)")
    print("=" * 70)
    
    data = load_data()
    
    if 'TNX' not in data:
        print("❌ 缺少国债收益率数据")
        return
    
    tnx = data['TNX']
    bond_yield = tnx.set_index('date')['close'] / 100  # 转为小数
    
    results = {}
    
    for name, df in data.items():
        if name == 'TNX':
            continue
        
        print(f"\n{'='*50}")
        print(f"ETF: {name}")
        print(f"{'='*50}")
        
        # 对齐日期（忽略时间，只比较日期）
        df_aligned = df.copy()
        df_aligned['date_only'] = pd.to_datetime(df_aligned['date']).dt.date
        bond_aligned = bond_yield.copy()
        bond_aligned.index = pd.to_datetime(bond_aligned.index).date
        
        etf_dates = set(df_aligned['date_only'])
        tnx_dates = set(bond_aligned.index)
        common_dates = sorted(list(etf_dates & tnx_dates))
        
        if len(common_dates) < 100:
            print(f"  共同交易日不足: {len(common_dates)}")
            continue
        
        # 筛选共同日期
        df_aligned = df_aligned[df_aligned['date_only'].isin(common_dates)].sort_values('date').reset_index(drop=True)
        # 去掉临时列
        df_aligned = df_aligned.drop(columns=['date_only'])
        bond_aligned = bond_aligned[bond_aligned.index.isin(common_dates)]
        
        print(f"  共同交易日: {len(common_dates)}天")
        
        # 策略1: 股债利差
        print(f"\n  [策略1] 股债利差择时")
        strategy1 = EquityBondSpreadStrategy(pe_base=15.0)
        signals1 = strategy1.generate(df_aligned, bond_aligned)
        bt1 = Backtester()
        r1 = bt1.run(signals1, df_aligned)
        print(f"      收益率: {r1['total_return']:>8.2f}%  基准: {r1['benchmark']:>8.2f}%  相对: {r1['total_return']-r1['benchmark']:>+8.2f}%  夏普: {r1['sharpe']:>6.2f}  回撤: {r1['max_drawdown']:>7.2f}%")
        results[f'{name}_spread'] = r1
        
        # 策略2: 趋势跟踪
        print(f"  [策略2] 趋势跟踪(MA20/60)")
        strategy2 = TrendFollowingStrategy(20, 60)
        signals2 = strategy2.generate(df_aligned)
        r2 = bt1.run(signals2, df_aligned)
        print(f"      收益率: {r2['total_return']:>8.2f}%  基准: {r2['benchmark']:>8.2f}%  相对: {r2['total_return']-r2['benchmark']:>+8.2f}%  夏普: {r2['sharpe']:>6.2f}  回撤: {r2['max_drawdown']:>7.2f}%")
        results[f'{name}_trend'] = r2
        
        # 策略3: 双均线
        print(f"  [策略3] 双均线(MA10/60)")
        strategy3 = DualMovingAverageStrategy(10, 60)
        signals3 = strategy3.generate(df_aligned)
        r3 = bt1.run(signals3, df_aligned)
        print(f"      收益率: {r3['total_return']:>8.2f}%  基准: {r3['benchmark']:>8.2f}%  相对: {r3['total_return']-r3['benchmark']:>+8.2f}%  夏普: {r3['sharpe']:>6.2f}  回撤: {r3['max_drawdown']:>7.2f}%")
        results[f'{name}_ma'] = r3
        
        # 策略4: 动量
        print(f"  [策略4] 动量策略")
        strategy4 = MomentumStrategy(20)
        signals4 = strategy4.generate(df_aligned)
        r4 = bt1.run(signals4, df_aligned)
        print(f"      收益率: {r4['total_return']:>8.2f}%  基准: {r4['benchmark']:>8.2f}%  相对: {r4['total_return']-r4['benchmark']:>+8.2f}%  夏普: {r4['sharpe']:>6.2f}  回撤: {r4['max_drawdown']:>7.2f}%")
        results[f'{name}_momentum'] = r4
        
        # 策略5: 综合策略(无利差)
        print(f"  [策略5] 综合策略(趋势+动量)")
        strategy5 = CombinedStrategy(use_spread=False)
        signals5 = strategy5.generate(df_aligned)
        r5 = bt1.run(signals5, df_aligned)
        print(f"      收益率: {r5['total_return']:>8.2f}%  基准: {r5['benchmark']:>8.2f}%  相对: {r5['total_return']-r5['benchmark']:>+8.2f}%  夏普: {r5['sharpe']:>6.2f}  回撤: {r5['max_drawdown']:>7.2f}%")
        results[f'{name}_combined'] = r5
    
    # 汇总
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    print(f"\n{'ETF':<8}{'策略':<15}{'收益率':>10}{'基准':>10}{'相对':>10}{'夏普':>8}{'最大回撤':>10}")
    print("-" * 75)
    
    for key, res in sorted(results.items()):
        etf, strat = key.rsplit('_', 1)
        print(f"{etf:<8}{strat:<15}{res['total_return']:>9.2f}%{res['benchmark']:>10.2f}%{res['total_return']-res['benchmark']:>+10.2f}% {res['sharpe']:>7.2f} {res['max_drawdown']:>9.2f}%")
    
    # 找出最佳策略
    print("\n🏆 最佳策略 (按夏普比率)")
    best = max(results.items(), key=lambda x: x[1]['sharpe'])
    print(f"  {best[0]}: 夏普 {best[1]['sharpe']:.2f}, 收益率 {best[1]['total_return']:.2f}%")
    
    return results

if __name__ == '__main__':
    run_all_strategies()
