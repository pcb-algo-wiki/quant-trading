"""
估值择时策略回测
使用现有ETF缓存数据 + 模拟国债收益率

策略：
1. 股债利差择时（ValueTimingStrategy）
2. PE百分位择时（PEPercentileStrategy）
3. 多因子综合（MultiFactorWithValuation）
"""

import sys
sys.path.insert(0, '/Users/tanwei/quant-trading')

import pandas as pd
import numpy as np
from strategies.value_timing import (
    ValueTimingStrategy,
    PEPercentileStrategy, 
    MultiFactorWithValuation,
    Backtester
)
import warnings
warnings.filterwarnings('ignore')

def load_etf_data():
    """加载ETF数据"""
    cache_files = {
        '510300': '/Users/tanwei/quant-trading/data/cache/etf_510300.pkl',
        '510500': '/Users/tanwei/quant-trading/data/cache/etf_510500.pkl',
        '159915': '/Users/tanwei/quant-trading/data/cache/etf_159915.pkl',
    }
    
    data = {}
    for code, path in cache_files.items():
        df = pd.read_pickle(path)
        df = df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
        data[code] = df
    return data

def get_bond_yield_series(dates, base_yield=0.028):
    """生成国债收益率序列（简化：固定2.8%）"""
    # 实际应用中应使用真实国债收益率
    return pd.Series(base_yield, index=dates)

def run_single_strategy(data, name, strategy_class, **kwargs):
    """运行单个策略回测"""
    df = data[name].copy()
    
    # 生成信号
    strategy = strategy_class(**kwargs)
    signals = strategy.generate(df)
    
    # 回测
    backtester = Backtester(initial_capital=100000)
    result = backtester.run(signals, df)
    
    return result

def main():
    print("=" * 60)
    print("估值择时多因子策略回测")
    print("=" * 60)
    
    data = load_etf_data()
    
    # 对齐日期
    common_dates = None
    for df in data.values():
        dates = set(df['date'])
        common_dates = dates if common_dates is None else common_dates.intersection(dates)
    common_dates = sorted(list(common_dates))
    warmup = 60
    
    print(f"共同交易日: {len(common_dates)}天, 预热: {warmup}天")
    
    results = {}
    
    # 策略1: 股债利差择时
    print("\n" + "-" * 40)
    print("策略1: 股债利差择时")
    print("-" * 40)
    
    for name, df in data.items():
        # 生成国债收益率（简化版）
        bond_yield = get_bond_yield_series(df['date'])
        
        strategy = ValueTimingStrategy(lookback=252)
        signals = strategy.generate(df, bond_yield)
        
        backtester = Backtester()
        result = backtester.run(signals, df)
        
        print(f"\n  {name}:")
        print(f"    收益率: {result['total_return']:.2f}%")
        print(f"    基准:   {result['benchmark']:.2f}%")
        print(f"    相对:   {result['total_return'] - result['benchmark']:.2f}%")
        print(f"    夏普:   {result['sharpe']:.2f}")
        print(f"    最大回撤: {result['max_drawdown']:.2f}%")
        
        results[f'{name}_spread'] = result
    
    # 策略2: PE百分位择时
    print("\n" + "-" * 40)
    print("策略2: PE百分位择时")
    print("-" * 40)
    
    for name, df in data.items():
        strategy = PEPercentileStrategy(lookback=252, buy_threshold=0.3, sell_threshold=0.7)
        signals = strategy.generate(df)
        
        backtester = Backtester()
        result = backtester.run(signals, df)
        
        print(f"\n  {name}:")
        print(f"    收益率: {result['total_return']:.2f}%")
        print(f"    基准:   {result['benchmark']:.2f}%")
        print(f"    相对:   {result['total_return'] - result['benchmark']:.2f}%")
        print(f"    夏普:   {result['sharpe']:.2f}")
        print(f"    最大回撤: {result['max_drawdown']:.2f}%")
        
        results[f'{name}_pe'] = result
    
    # 策略3: 多因子综合
    print("\n" + "-" * 40)
    print("策略3: 多因子综合（估值+动量+趋势）")
    print("-" * 40)
    
    for name, df in data.items():
        strategy = MultiFactorWithValuation(
            valuation_weight=0.4,
            momentum_weight=0.3,
            trend_weight=0.3
        )
        signals = strategy.generate(df)
        
        backtester = Backtester()
        result = backtester.run(signals, df)
        
        print(f"\n  {name}:")
        print(f"    收益率: {result['total_return']:.2f}%")
        print(f"    基准:   {result['benchmark']:.2f}%")
        print(f"    相对:   {result['total_return'] - result['benchmark']:.2f}%")
        print(f"    夏普:   {result['sharpe']:.2f}")
        print(f"    最大回撤: {result['max_drawdown']:.2f}%")
        
        results[f'{name}_multi'] = result
    
    # 汇总
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    
    print(f"\n{'策略':<20} {'收益率':>10} {'基准':>10} {'相对':>10} {'夏普':>8} {'最大回撤':>10}")
    print("-" * 70)
    
    for key, res in results.items():
        print(f"{key:<20} {res['total_return']:>9.2f}% {res['benchmark']:>9.2f}% {res['total_return']-res['benchmark']:>+9.2f}% {res['sharpe']:>8.2f} {res['max_drawdown']:>9.2f}%")

if __name__ == '__main__':
    main()
