"""
多因子策略回测（简化版）
"""

import sys
sys.path.insert(0, '/Users/tanwei/quant-trading')

import pandas as pd
import numpy as np
from strategies.multi_factor import MultiFactorStrategy, MultiFactorBacktester
import warnings
warnings.filterwarnings('ignore')

def load_data():
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
        print(f"✅ {code}: {len(df)}行")
    return data

def run_portfolio():
    print("=" * 60)
    print("多因子策略 - 跨截面组合")
    print("=" * 60)
    
    data = load_data()
    
    common_dates = None
    for df in data.values():
        dates = set(df['date'])
        common_dates = dates if common_dates is None else common_dates.intersection(dates)
    common_dates = sorted(list(common_dates))
    warmup = 60
    
    print(f"共同交易日: {len(common_dates)}天 (预热{warmup}天)")
    
    # 构建价格字典
    prices = {}
    for name, df in data.items():
        for _, row in df.iterrows():
            d = row['date']
            if d not in prices:
                prices[d] = {}
            prices[d][name] = row['close']
    
    strategy = MultiFactorStrategy(rebalance_days=5)
    
    # 计算每日评分（预热期后）
    print("\n计算每日评分...")
    daily_scores = []
    for i, date in enumerate(common_dates):
        if i < warmup:
            daily_scores.append({name: 0 for name in data.keys()})
            continue
        
        scores = {}
        for name, df in data.items():
            subset = df[df['date'] <= date]
            if len(subset) >= 60:
                tail = subset.tail(60)
                factors = strategy._compute_factors(tail)
                score = strategy._score_factors(factors).iloc[-1]
                scores[name] = score
            else:
                scores[name] = 0
        daily_scores.append(scores)
    
    # 模拟交易
    print("模拟交易...")
    equity = 100000.0
    equity_curve = []
    current_holding = None
    entry_price = 0
    commission = 0.0003
    slippage = 0.0001
    
    for i, date in enumerate(common_dates):
        if i < warmup:
            equity_curve.append({'date': date, 'equity': equity, 'holding': None})
            continue
        
        scores = daily_scores[i]
        best_etf = max(scores, key=scores.get) if scores else None
        current_price = prices.get(date, {}).get(best_etf)
        
        if current_holding is None:
            if best_etf and current_price:
                current_holding = best_etf
                entry_price = current_price * (1 + slippage)
        else:
            holding_price = prices.get(date, {}).get(current_holding)
            
            if i % strategy.rebalance_days == 0:
                if best_etf != current_holding:
                    if holding_price:
                        ret = (holding_price - entry_price) / entry_price
                        equity *= (1 + ret)
                        equity *= (1 - commission)
                    
                    if best_etf and prices.get(date, {}).get(best_etf):
                        current_holding = best_etf
                        entry_price = prices[date][best_etf] * (1 + slippage)
                    else:
                        current_holding = None
        
        equity_curve.append({'date': date, 'equity': equity, 'holding': current_holding})
    
    # 平仓
    if current_holding:
        last_date = common_dates[-1]
        last_price = prices.get(last_date, {}).get(current_holding)
        if last_price:
            ret = (last_price - entry_price) / entry_price
            equity *= (1 + ret)
            equity *= (1 - commission)
    
    equity_df = pd.DataFrame(equity_curve)
    
    # 基准：等权持有
    benchmark_equity = 100000.0
    for name, df in data.items():
        first = df[df['date'] == common_dates[0]]['close'].values[0]
        last = df[df['date'] == common_dates[-1]]['close'].values[0]
        ret = (last / first - 1) / 3
        benchmark_equity *= (1 + ret)
    benchmark_return = (benchmark_equity / 100000 - 1) * 100
    
    strategy_return = (equity / 100000 - 1) * 100
    years = (len(common_dates) - warmup) / 252
    annual_return = ((equity / 100000) ** (1/years) - 1) * 100 if years > 0 else 0
    
    returns = equity_df['equity'].pct_change().dropna()
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    
    equity_df['peak'] = equity_df['equity'].cummax()
    equity_df['dd'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak'] * 100
    max_dd = equity_df['dd'].min()
    
    print(f"\n{'='*40}")
    print(f"回测结果:")
    print(f"  策略收益: {strategy_return:.2f}%")
    print(f"  买入持有基准: {benchmark_return:.2f}%")
    print(f"  相对收益: {strategy_return - benchmark_return:.2f}%")
    print(f"  年化收益: {annual_return:.2f}%")
    print(f"  夏普比率: {sharpe:.2f}")
    print(f"  最大回撤: {max_dd:.2f}%")
    print(f"  最终权益: ¥{equity:.2f}")

if __name__ == '__main__':
    run_portfolio()
