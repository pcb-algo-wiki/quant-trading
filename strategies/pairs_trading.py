"""
配对交易策略 (Pairs Trading)
原理：两只高度相关的资产，当价差偏离均值时入场，价差回归时平仓
- 做空高估资产，做多低估资产，天然对冲市场风险
- 只做同类ETF（如沪深300 vs 中证500）

用法:
    from strategies.pairs_trading import PairsTrading
    strategy = PairsTrading(asset1='510300', asset2='510500', lookback=60, entry_z=1.5, exit_z=0.5)
    signals = strategy.generate(data1, data2)
"""

import numpy as np
import pandas as pd
from typing import Tuple


class PairsTrading:
    """
    协整配对交易策略
    
    参数:
        lookback: 计算 hedge ratio 的历史窗口（天）
        entry_z: 入场阈值（标准差倍数）
        exit_z: 平仓阈值（标准差倍数）
        min_lookback: 最小数据窗口
    """
    
    def __init__(self, asset1: str = '510300', asset2: str = '510500',
                 lookback: int = 60, entry_z: float = 1.5, exit_z: float = 0.5,
                 min_lookback: int = 20):
        self.asset1 = asset1
        self.asset2 = asset2
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.min_lookback = min_lookback
    
    def _calculate_hedge_ratio(self, prices1: pd.Series, prices2: pd.Series, lookback: int) -> float:
        """用OLS计算对冲比率"""
        if len(prices1) < lookback:
            return 1.0
        x = prices1.iloc[-lookback:].values
        y = prices2.iloc[-lookback:].values
        # 简单线性回归: price1 = h * price2 + c
        x_mean, y_mean = x.mean(), y.mean()
        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)
        if denominator < 1e-10:
            return 1.0
        return numerator / denominator
    
    def _calculate_spread_zscore(self, prices1: pd.Series, prices2: pd.Series) -> pd.Series:
        """计算价差的Z-Score"""
        lookback = min(self.lookback, len(prices1) - 1)
        if lookback < self.min_lookback:
            return pd.Series(0, index=prices1.index)
        
        # 滚动计算hedge ratio和价差
        z_scores = []
        for i in range(len(prices1)):
            if i < lookback:
                z_scores.append(0.0)
                continue
            
            p1 = prices1.iloc[i-lookback:i+1]
            p2 = prices2.iloc[i-lookback:i+1]
            
            h = self._calculate_hedge_ratio(p1, p2, lookback)
            spread = p1.values - h * p2.values
            spread_mean = spread.mean()
            spread_std = spread.std()
            
            if spread_std < 1e-10:
                z_scores.append(0.0)
            else:
                current_spread = prices1.iloc[i] - h * prices2.iloc[i]
                z = (current_spread - spread_mean) / spread_std
                z_scores.append(z)
        
        return pd.Series(z_scores, index=prices1.index)
    
    def generate(self, data1: pd.DataFrame, data2: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data1: 资产1的OHLC数据（含close列）
            data2: 资产2的OHLC数据（含close列）
            
        Returns:
            DataFrame with columns: signal, spread, zscore, position1, position2
            signal: 1=做多价差(spread), -1=做空价差, 0=空仓
        """
        # 提取收盘价
        if 'close' in data1.columns:
            p1 = data1['close'].copy()
        else:
            p1 = data1.iloc[:, 3]  # 默认第4列是close
        
        if 'close' in data2.columns:
            p2 = data2['close'].copy()
        else:
            p2 = data2.iloc[:, 3]
        
        # 对齐索引
        common_idx = p1.index.intersection(p2.index)
        p1 = p1.loc[common_idx]
        p2 = p2.loc[common_idx]
        
        # 计算Z-Score
        zscore = self._calculate_spread_zscore(p1, p2)
        
        # 生成信号
        signals = pd.DataFrame(index=common_idx)
        signals['spread'] = p1 - p2
        signals['zscore'] = zscore
        signals['signal'] = 0  # 0=空仓
        
        # 状态变量：是否持仓
        position = 0  # 1=做多价差, -1=做空价差, 0=空仓
        
        for i in range(len(signals)):
            z = zscore.iloc[i]
            
            if position == 0:
                # 空仓：根据Z-score入场
                if z > self.entry_z:
                    position = -1  # 做空价差（价差过高，做空p1做多p2）
                elif z < -self.entry_z:
                    position = 1   # 做多价差（价差过低，做多p1做空p2）
            
            elif position == 1:
                # 做多价差持仓
                if z > -self.exit_z:
                    position = 0  # 价差回归，平仓
                # z < -entry_z 时继续持有
            
            elif position == -1:
                # 做空价差持仓
                if z < self.exit_z:
                    position = 0  # 价差回归，平仓
                # z > entry_z 时继续持有
            
            signals.iloc[i, signals.columns.get_loc('signal')] = position
        
        # position1: 资产1的仓位（1=做多, -1=做空, 0=空仓）
        # position2: 资产2的仓位（与position1相反）
        signals['position1'] = signals['signal']  # 做多价差=做多p1
        signals['position2'] = -signals['signal']  # 做空价差=做空p2
        
        return signals.reset_index(drop=True)
    
    def generate_batch(self, prices1: pd.Series, prices2: pd.Series) -> pd.DataFrame:
        """
        批量生成信号（一次性计算，适合回测）
        比generate()快，适合大数据量回测
        """
        common_idx = prices1.index.intersection(prices2.index)
        p1 = prices1.loc[common_idx].copy()
        p2 = prices2.loc[common_idx].copy()
        
        lookback = min(self.lookback, len(p1) - 1)
        
        # 预计算滚动hedge ratio和Z-score
        spread = pd.Series(np.nan, index=common_idx)
        zscore = pd.Series(np.nan, index=common_idx)
        
        for i in range(lookback, len(p1)):
            window_p1 = p1.iloc[i-lookback:i+1]
            window_p2 = p2.iloc[i-lookback:i+1]
            
            h = self._calculate_hedge_ratio(window_p1, window_p2, lookback)
            window_spread = window_p1.values - h * window_p2.values
            
            current_spread = p1.iloc[i] - h * p2.iloc[i]
            spread.iloc[i] = current_spread
            
            z = (current_spread - window_spread.mean()) / (window_spread.std() + 1e-10)
            zscore.iloc[i] = z
        
        # 填充前面的值为0
        spread.fillna(0, inplace=True)
        zscore.fillna(0, inplace=True)
        
        # 生成信号
        signals = pd.DataFrame(index=common_idx)
        signals['spread'] = spread
        signals['zscore'] = zscore
        signals['signal'] = 0.0
        
        position = 0
        signal_list = []
        for z in zscore:
            if position == 0:
                if z > self.entry_z:
                    position = -1
                elif z < -self.entry_z:
                    position = 1
            elif position == 1:
                if z > -self.exit_z:
                    position = 0
            elif position == -1:
                if z < self.exit_z:
                    position = 0
            signal_list.append(position)
        
        signals['signal'] = signal_list
        signals['position1'] = signals['signal']
        signals['position2'] = -signals['signal']
        
        return signals.reset_index(drop=True)


class PairsBacktester:
    """
    配对交易回测引擎
    支持做空、做多、双边同时持仓
    
    交易逻辑：
    - signal=1（做多价差）：做多asset1，做空asset2
    - signal=-1（做空价差）：做空asset1，做多asset2
    - signal=0：空仓，双边平仓
    """
    
    def __init__(self, initial_capital: float = 100000.0, commission: float = 0.0003):
        self.initial_capital = initial_capital
        self.commission = commission  # 手续费（含印花税）
    
    def run(self, signals: pd.DataFrame, prices1: pd.DataFrame, 
            prices2: pd.DataFrame) -> dict:
        """
        运行回测
        
        Args:
            signals: 配对交易信号（含signal, position1, position2列）
            prices1: 资产1的OHLC数据
            prices2: 资产2的OHLC数据
            
        Returns:
            回测结果字典
        """
        # 对齐数据
        common_idx = signals.index.intersection(prices1.index).intersection(prices2.index)
        
        sig = signals.loc[common_idx].reset_index(drop=True)
        p1 = prices1.loc[common_idx].reset_index(drop=True)
        p2 = prices2.loc[common_idx].reset_index(drop=True)
        
        n = len(sig)
        equity = self.initial_capital
        equity_curve = []
        trades = []
        position = 0
        entry_price1 = 0
        entry_price2 = 0
        
        for i in range(n):
            current_signal = sig['signal'].iloc[i]
            close1 = p1['close'].iloc[i]
            close2 = p2['close'].iloc[i]
            date = p1['date'].iloc[i] if 'date' in p1.columns else common_idx[i]
            
            # 入场/持仓变化
            if current_signal != position:
                if position != 0:
                    # 平仓
                    pnl1 = (close1 - entry_price1) * position * 0.5  # 50%仓位
                    pnl2 = (close2 - entry_price2) * (-position) * 0.5
                    
                    # 手续费
                    cost = (abs(pnl1) + abs(pnl2)) * self.commission
                    
                    trades.append({
                        'date': date,
                        'type': 'long_spread' if position == 1 else 'short_spread',
                        'pnl': pnl1 + pnl2 - cost,
                        'equity': equity + pnl1 + pnl2 - cost
                    })
                    equity += pnl1 + pnl2 - cost
                
                if current_signal != 0:
                    # 开仓
                    entry_price1 = close1
                    entry_price2 = close2
                
                position = current_signal
            
            equity_curve.append({
                'date': date,
                'equity': equity,
                'position': position
            })
        
        # 最终平仓
        if position != 0:
            close1 = p1['close'].iloc[-1]
            close2 = p2['close'].iloc[-1]
            date = p1['date'].iloc[-1] if 'date' in p1.columns else common_idx[-1]
            
            pnl1 = (close1 - entry_price1) * position * 0.5
            pnl2 = (close2 - entry_price2) * (-position) * 0.5
            cost = (abs(pnl1) + abs(pnl2)) * self.commission
            
            trades.append({
                'date': date,
                'type': 'close',
                'pnl': pnl1 + pnl2 - cost,
                'equity': equity + pnl1 + pnl2 - cost
            })
            equity += pnl1 + pnl2 - cost
        
        # 计算统计
        equity_df = pd.DataFrame(equity_curve)
        
        # 买入持有基准
        buy_hold_p1 = (p1['close'].iloc[-1] / p1['close'].iloc[0] - 1) * 100
        buy_hold_p2 = (p2['close'].iloc[-1] / p2['close'].iloc[0] - 1) * 100
        benchmark = (buy_hold_p1 + buy_hold_p2) / 2
        
        # 策略收益
        strategy_return = (equity / self.initial_capital - 1) * 100
        
        return {
            'equity_curve': equity_df,
            'trades': pd.DataFrame(trades),
            'total_return': strategy_return,
            'benchmark': benchmark,
            'n_trades': len(trades),
            'final_equity': equity,
        }
