"""
配对交易回测脚本
测试510300(沪深300) vs 510500(中证500)的配对交易

入场逻辑：
- Z-Score > 1.5：做空价差（沪深300相对高估，做空沪深300+做多中证500）
- Z-Score < -1.5：做多价差（沪深300相对低估，做多沪深300+做空中证500）
- Z-Score回归到0.5以内：平仓
"""

import sys
sys.path.insert(0, '/Users/tanwei/quant-trading')

import pandas as pd
import numpy as np
from strategies.pairs_trading import PairsTrading, PairsBacktester
def load_etf_data():
    """加载本地缓存的ETF数据"""
    # 直接从缓存加载，避免fetch_etf的日期过滤逻辑问题
    cache_files = {
        '510300': '/Users/tanwei/quant-trading/data/cache/etf_510300.pkl',
        '510500': '/Users/tanwei/quant-trading/data/cache/etf_510500.pkl',
    }
    
    data = {}
    for code, path in cache_files.items():
        df = pd.read_pickle(path)
        # 去重（同一日期多条记录）
        df = df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
        data[code] = df
        print(f"✅ {code}: {len(df)}行, {df['date'].min().date()} ~ {df['date'].max().date()}")
    
    return data

def run_backtest():
    """运行配对交易回测"""
    print("=" * 60)
    print("配对交易回测：沪深300 vs 中证500")
    print("=" * 60)
    
    # 加载数据
    data = load_etf_data()
    if len(data) < 2:
        print("数据不足")
        return
    
    df1 = data['510300']
    df2 = data['510500']
    
    # 对齐数据
    common_dates = set(df1['date']).intersection(set(df2['date']))
    df1 = df1[df1['date'].isin(common_dates)].sort_values('date').reset_index(drop=True)
    df2 = df2[df2['date'].isin(common_dates)].sort_values('date').reset_index(drop=True)
    
    print(f"\n有效交易日: {len(df1)}天")
    print(f"时间范围: {df1['date'].iloc[0]} ~ {df1['date'].iloc[-1]}")
    
    # 配对交易策略
    print("\n" + "-" * 40)
    print("策略参数:")
    print("  回看窗口: 60天")
    print("  入场阈值: Z-Score > 1.5 或 < -1.5")
    print("  平仓阈值: Z-Score回归到 ±0.5")
    print("-" * 40)
    
    strategy = PairsTrading(
        asset1='510300',
        asset2='510500',
        lookback=60,
        entry_z=1.5,
        exit_z=0.5
    )
    
    signals = strategy.generate_batch(df1['close'], df2['close'])
    
    # 入场统计
    n_long = (signals['signal'] == 1).sum()
    n_short = (signals['signal'] == -1).sum()
    n_flat = (signals['signal'] == 0).sum()
    print(f"\n信号分布:")
    print(f"  做多价差: {n_long}天 ({n_long/len(signals)*100:.1f}%)")
    print(f"  做空价差: {n_short}天 ({n_short/len(signals)*100:.1f}%)")
    print(f"  空仓: {n_flat}天 ({n_flat/len(signals)*100:.1f}%)")
    
    # 回测
    backtester = PairsBacktester(initial_capital=100000, commission=0.0003)
    result = backtester.run(signals, df1, df2)
    
    print(f"\n{'='*40}")
    print("回测结果:")
    print(f"{'='*40}")
    print(f"  初始资金: ¥100,000")
    print(f"  最终权益: ¥{result['final_equity']:.2f}")
    print(f"  策略收益率: {result['total_return']:.2f}%")
    print(f"  买入持有基准: {result['benchmark']:.2f}%")
    print(f"  相对收益: {result['total_return'] - result['benchmark']:.2f}%")
    print(f"  交易次数: {result['n_trades']}")
    
    # 计算年化收益率
    years = len(df1) / 252
    annual_return = ((result['final_equity'] / 100000) ** (1/years) - 1) * 100
    print(f"  年化收益率: {annual_return:.2f}%")
    
    # 计算夏普比率
    equity_df = result['equity_curve']
    returns = equity_df['equity'].pct_change().dropna()
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    print(f"  夏普比率: {sharpe:.2f}")
    
    # 最大回撤
    equity_df['peak'] = equity_df['equity'].cummax()
    equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak'] * 100
    max_dd = equity_df['drawdown'].min()
    print(f"  最大回撤: {max_dd:.2f}%")
    
    # 交易记录
    if len(result['trades']) > 0:
        print(f"\n交易记录 (前10笔):")
        trades_df = result['trades'].sort_values('date')
        for _, row in trades_df.head(10).iterrows():
            print(f"  {row['date']}: {row['type']:15s} pnl={row['pnl']:8.2f} equity={row['equity']:.2f}")
    
    # 统计分析
    if len(result['trades']) > 0:
        win_rate = (result['trades']['pnl'] > 0).mean() * 100
        avg_win = result['trades'][result['trades']['pnl'] > 0]['pnl'].mean()
        avg_loss = result['trades'][result['trades']['pnl'] < 0]['pnl'].mean()
        
        print(f"\n交易统计:")
        print(f"  胜率: {win_rate:.1f}%")
        print(f"  平均盈利: ¥{avg_win:.2f}" if not np.isnan(avg_win) else "  平均盈利: N/A")
        print(f"  平均亏损: ¥{avg_loss:.2f}" if not np.isnan(avg_loss) else "  平均亏损: N/A")
        
        if not np.isnan(avg_win) and not np.isnan(avg_loss) and avg_loss != 0:
            profit_factor = abs(avg_win / avg_loss)
            print(f"  盈亏比: {profit_factor:.2f}")
    
    print("\n" + "=" * 60)
    
    # 多参数扫描
    print("\n多参数扫描...")
    best_sharpe = -999
    best_params = None
    
    for lookback in [30, 60, 90, 120]:
        for entry_z in [1.0, 1.5, 2.0]:
            for exit_z in [0.3, 0.5, 0.8]:
                strategy = PairsTrading(
                    asset1='510300',
                    asset2='510500',
                    lookback=lookback,
                    entry_z=entry_z,
                    exit_z=exit_z
                )
                
                signals = strategy.generate_batch(df1['close'], df2['close'])
                result = backtester.run(signals, df1, df2)
                
                equity_df = result['equity_curve']
                returns = equity_df['equity'].pct_change().dropna()
                
                if len(returns) > 0 and returns.std() > 0:
                    sharpe = returns.mean() / returns.std() * np.sqrt(252)
                    
                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_params = (lookback, entry_z, exit_z, result)
    
    if best_params:
        lookback, entry_z, exit_z, result = best_params
        print(f"\n🏆 最佳参数:")
        print(f"  回看窗口: {lookback}天")
        print(f"  入场阈值: {entry_z}")
        print(f"  平仓阈值: {exit_z}")
        print(f"  夏普比率: {best_sharpe:.2f}")
        print(f"  收益率: {result['total_return']:.2f}%")
        print(f"  最终权益: ¥{result['final_equity']:.2f}")
    
    return result

if __name__ == '__main__':
    run_backtest()
