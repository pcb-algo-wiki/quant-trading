"""
估值择时策略 - 真实数据版
使用Yahoo Finance获取的:
- 真实ETF价格数据
- 真实10年国债收益率(^TNX)

原理:
股债利差 = 股票收益率(1/PE) - 国债收益率
利差高 → 股票相对便宜 → 高仓位
利差低 → 股票相对昂贵 → 低仓位

注意: PE使用模拟值(基于价格估算)，真实PE需要聚宽/米筐
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional
import os, pickle

CACHE_DIR = '/Users/tanwei/quant-trading/data/cache'

def load_yahoo_data():
    """加载Yahoo Finance缓存数据"""
    data = {}
    for name in ['510300', '510500', '159915']:
        path = f'{CACHE_DIR}/yahoo_{name}.pkl'
        if os.path.exists(path):
            data[name] = pd.read_pickle(path)
    # 国债收益率
    tnx_path = f'{CACHE_DIR}/yahoo_TNX.pkl'
    if os.path.exists(tnx_path):
        data['TNX'] = pd.read_pickle(tnx_path)
    return data

class EquityBondSpreadStrategy:
    """
    股债利差择时策略
    
    使用真实的10年国债收益率 + 模拟的股票收益率
    虽然PE是估算，但利差的变化趋势是有参考价值的
    """
    
    def __init__(self, pe_base: float = 15.0, lookback: int = 252):
        self.pe_base = pe_base  # 基准PE
        self.lookback = lookback
    
    def estimate_pe_from_price(self, price: pd.Series, base_price: float, base_pe: float) -> pd.Series:
        """用价格估算PE (假设PE与价格成正比)"""
        return (price / base_price) * base_pe
    
    def generate(self, price_data: pd.DataFrame, bond_yield: pd.Series) -> pd.DataFrame:
        """
        生成信号
        
        Args:
            price_data: ETF价格数据
            bond_yield: 国债收益率 Series，index为date
        """
        close = price_data['close']
        
        # 估算股票盈利收益率 E/P = 1/PE
        base_price = close.iloc[0]
        estimated_pe = self.estimate_pe_from_price(close, base_price, self.pe_base)
        equity_yield = 1.0 / estimated_pe
        
        # 对齐：用日期列而不是索引
        if 'date' in price_data.columns:
            price_dates = pd.to_datetime(price_data['date']).dt.date
        else:
            price_dates = pd.Series(close.index, index=close.index)
        
        # bond_yield的index是date
        bond_dates = pd.to_datetime(bond_yield.index).date
        
        # 找共同日期
        common = set(price_dates) & set(bond_dates)
        
        if len(common) == 0:
            # 返回空信号
            return pd.DataFrame({
                'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
                'close': close,
                'spread': 0,
                'position': 0,
                'signal': 0,
            })
        
        # 筛选共同日期
        mask = price_dates.isin(common)
        close_aligned = close[mask].reset_index(drop=True)
        ey_aligned = equity_yield[mask].reset_index(drop=True)
        
        # 获取对应的国债收益率
        by_values = []
        for d in price_dates[mask]:
            # 找最近的国债数据
            matches = bond_yield.index[pd.to_datetime(bond_yield.index).date == d]
            if len(matches) > 0:
                by_values.append(bond_yield.iloc[bond_yield.index.get_loc(matches[0])])
            else:
                by_values.append(by_values[-1] if by_values else 0.03)
        
        spread = ey_aligned - pd.Series(by_values)
        
        # 计算利差的Z-score
        spread_ma = spread.rolling(20).mean()
        spread_std = spread.rolling(20).std()
        spread_zscore = (spread - spread_ma) / (spread_std + 1e-10)
        
        # 仓位规则
        position = pd.Series(0.0, index=spread.index)
        position[spread_zscore > 1.0] = 1.0
        position[(spread_zscore >= 0) & (spread_zscore <= 1.0)] = 0.5
        position[(spread_zscore < 0) & (spread_zscore >= -1.0)] = 0.3
        position[spread_zscore < -1.0] = 0.0
        
        signal = position.diff().fillna(0)
        signal[signal > 0] = 1
        signal[signal < 0] = -1
        
        result = pd.DataFrame({
            'date': price_dates[mask].values,
            'close': close_aligned.values,
            'spread': spread.values,
            'spread_zscore': spread_zscore.values,
            'equity_yield': ey_aligned.values,
            'bond_yield': by_values,
            'position': position.values,
            'signal': signal.values,
        })
        
        return result


class TrendFollowingStrategy:
    """
    趋势跟踪策略 - 使用真实价格数据
    
    规则:
    - MA20 > MA60 → 上升趋势 → 持仓
    - MA20 < MA60 → 下降趋势 → 空仓
    """
    
    def __init__(self, ma_short: int = 20, ma_long: int = 60):
        self.ma_short = ma_short
        self.ma_long = ma_long
    
    def generate(self, price_data: pd.DataFrame) -> pd.DataFrame:
        close = price_data['close']
        
        ma20 = close.rolling(self.ma_short).mean()
        ma60 = close.rolling(self.ma_long).mean()
        
        # 趋势信号: MA金叉/死叉
        trend = pd.Series(0, index=close.index)
        trend[ma20 > ma60] = 1   # 上升趋势
        trend[ma20 <= ma60] = 0  # 下降趋势
        
        # 过滤假信号：需要连续2天确认
        trend_filtered = trend.copy()
        for i in range(1, len(trend_filtered)):
            if trend.iloc[i] != trend.iloc[i-1]:
                trend_filtered.iloc[i] = trend.iloc[i-1]
        
        # 信号
        signal = trend_filtered.diff().fillna(0)
        signal[signal > 0] = 1
        signal[signal < 0] = -1
        
        return pd.DataFrame({
            'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
            'close': close,
            'ma20': ma20,
            'ma60': ma60,
            'trend': trend_filtered,
            'signal': signal,
            'position': trend_filtered,
        })


class DualMovingAverageStrategy:
    """双均线策略"""
    
    def __init__(self, short: int = 10, long: int = 60):
        self.short = short
        self.long = long
    
    def generate(self, price_data: pd.DataFrame) -> pd.DataFrame:
        close = price_data['close']
        
        ma_short = close.rolling(self.short).mean()
        ma_long = close.rolling(self.long).mean()
        
        position = (ma_short > ma_long).astype(int)
        signal = position.diff().fillna(0)
        
        return pd.DataFrame({
            'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
            'close': close,
            'ma_short': ma_short,
            'ma_long': ma_long,
            'position': position,
            'signal': signal,
        })


class MomentumStrategy:
    """
    动量策略
    
    规则:
    - 20日动量为正 → 持仓
    - 20日动量为负 → 空仓
    """
    
    def __init__(self, window: int = 20):
        self.window = window
    
    def generate(self, price_data: pd.DataFrame) -> pd.DataFrame:
        close = price_data['close']
        
        momentum = close.pct_change(self.window)
        position = (momentum > 0).astype(int)
        signal = position.diff().fillna(0)
        
        return pd.DataFrame({
            'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
            'close': close,
            'momentum': momentum,
            'position': position,
            'signal': signal,
        })


class CombinedStrategy:
    """
    综合策略: 趋势 + 动量 + 利差择时
    
    三个信号等权:
    - 趋势信号 (MA20 > MA60)
    - 动量信号 (20日动量 > 0)
    - 利差信号 (股债利差 > 0)
    
    仓位 = 平均信号值
    """
    
    def __init__(self, use_spread: bool = False):
        self.use_spread = use_spread
    
    def generate(self, price_data: pd.DataFrame, 
                 bond_yield: pd.Series = None,
                 pe_base: float = 15.0) -> pd.DataFrame:
        close = price_data['close']
        n = len(close)
        
        # 1. 趋势信号
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        trend_signal = (ma20 > ma60).astype(float).values
        
        # 2. 动量信号
        momentum = close.pct_change(20)
        momentum_signal = (momentum > 0).astype(float).values
        
        # 3. 利差信号
        if self.use_spread and bond_yield is not None:
            common_idx = close.index.intersection(bond_yield.index)
            base_price = close.iloc[0]
            estimated_pe = (close.loc[common_idx] / base_price) * pe_base
            ey = 1.0 / estimated_pe
            by = bond_yield.loc[common_idx].values
            spread = ey.values - by
            spread_signal = (spread > 0).astype(float)
            spread_signal_full = pd.Series(0.5, index=close.index)
            spread_signal_full.loc[common_idx] = spread_signal
            spread_signal_arr = spread_signal_full.values
        else:
            spread_signal_arr = np.ones(n) * 0.5  # 中性
        
        # 综合信号
        combined = (trend_signal + momentum_signal + spread_signal_arr) / 3
        
        # 仓位: >0.6 → 持仓, <0.4 → 空仓, 中间 → 持有50%
        position = pd.Series(0.0, index=close.index)
        position[combined > 0.6] = 1.0
        position[combined < 0.4] = 0.0
        position[(combined >= 0.4) & (combined <= 0.6)] = 0.5
        
        signal = pd.Series(0, index=close.index)
        diff = position.diff().fillna(0)
        signal[diff > 0] = 1
        signal[diff < 0] = -1
        
        return pd.DataFrame({
            'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
            'close': close,
            'trend_signal': trend_signal,
            'momentum_signal': momentum_signal,
            'spread_signal': spread_signal_arr,
            'combined': combined,
            'position': position,
            'signal': signal,
        })


class Backtester:
    """回测引擎"""
    
    def __init__(self, initial_capital: float = 100000.0,
                 commission: float = 0.0003,
                 slippage: float = 0.0001):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
    
    def run(self, signals: pd.DataFrame, price_data: pd.DataFrame) -> dict:
        # 对齐
        sig = signals.copy()
        px = price_data.copy()
        
        # 确保有date列
        if 'date' in px.columns:
            px = px.set_index('date')
        if 'date' in sig.columns:
            sig = sig.set_index('date')
        
        # 确保索引是同类型的
        if px.index.dtype != sig.index.dtype:
            try:
                px.index = pd.to_datetime(px.index)
                sig.index = pd.to_datetime(sig.index)
            except:
                pass
        
        common_idx = px.index.intersection(sig.index)
        if len(common_idx) == 0:
            return {
                'equity_curve': pd.DataFrame(),
                'total_return': 0, 'benchmark': 0, 'sharpe': 0,
                'max_drawdown': 0, 'final_equity': self.initial_capital,
            }
        
        sig = sig.loc[common_idx]
        px = px.loc[common_idx]
        
        equity = self.initial_capital
        equity_curve = []
        position = 0
        entry_price = 0
        
        for i, date in enumerate(common_idx):
            target_pos = sig.loc[date, 'position']
            close = px.loc[date, 'close']
            
            if target_pos != position:
                if position > 0:
                    ret = (close * (1 - self.slippage) - entry_price) / entry_price
                    equity *= (1 + ret)
                    equity *= (1 - self.commission)
                
                if target_pos > 0:
                    position = target_pos
                    entry_price = close * (1 + self.slippage)
                else:
                    position = 0
                    entry_price = 0
            
            if position > 0:
                current_equity = equity * (close / entry_price)
            else:
                current_equity = equity
            
            equity_curve.append({'date': date, 'equity': current_equity, 'position': position})
        
        equity_df = pd.DataFrame(equity_curve)
        
        buy_hold = (px['close'].iloc[-1] / px['close'].iloc[0] - 1) * 100
        strategy_return = (equity_df['equity'].iloc[-1] / self.initial_capital - 1) * 100
        
        returns = equity_df['equity'].pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['dd'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak'] * 100
        max_dd = equity_df['dd'].min()
        
        return {
            'equity_curve': equity_df,
            'total_return': strategy_return,
            'benchmark': buy_hold,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
            'final_equity': equity_df['equity'].iloc[-1],
        }
