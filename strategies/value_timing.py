"""
估值择时多因子策略
核心：基于A股市场估值水平（股债利差、PE百分位）进行仓位管理

因子：
1. 估值因子：股债利差（股票收益率 vs 债券收益率）
2. 动量因子：20日/60日动量
3. 趋势因子：MA状态

原理（已有学术和实盘验证）：
- 股债利差高 → 股票相对便宜 → 高仓位
- 股债利差低 → 股票相对昂贵 → 低仓位

用法:
    from strategies.value_timing import ValueTimingStrategy
    strategy = ValueTimingStrategy()
    signals = strategy.generate(price_data, bond_yield)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


class ValueTimingStrategy:
    """
    估值择时多因子策略
    
    核心逻辑：
    1. 计算股票盈利收益率 (E/P = 1/PE)
    2. 计算股债利差 = E/P - 10年国债收益率
    3. 利差高于历史中位数 → 股票低估 → 增加仓位
    4. 利差低于历史中位数 → 股票高估 → 减少仓位
    
    仓位规则：
    - 利差 > 75%分位：满仓（100%）
    - 利差 50-75%分位：标准仓位（80%）
    - 利差 25-50%分位：低仓位（50%）
    - 利差 < 25%分位：清仓（0%）
    """
    
    def __init__(self, lookback: int = 252,
                 entry_quantile: float = 0.25,
                 exit_quantile: float = 0.75,
                 min_position: float = 0.0,
                 max_position: float = 1.0):
        """
        Args:
            lookback: 历史窗口（天）
            entry_quantile: 入场阈值（利差低于此分位时离场）
            exit_quantile: 离场阈值（利差高于此分位时入场）
            min_position: 最小仓位
            max_position: 最大仓位
        """
        self.lookback = lookback
        self.entry_quantile = entry_quantile
        self.exit_quantile = exit_quantile
        self.min_position = min_position
        self.max_position = max_position
    
    def calculate_equity_yield(self, price: pd.Series, pe_proxy: float = 15.0) -> pd.Series:
        """
        计算股票盈利收益率（E/P）
        PE_proxy: 如果没有真实PE，用默认15倍
        
        真实PE获取方式：
        - 中证指数官网历史数据
        - 聚宽/米筐API（需账号）
        - 乐咕乐股/乌龟量化（免费）
        """
        # 简化：使用1/PE作为盈利收益率
        # 如果有真实PE数据，替换这里
        equity_yield = 1.0 / pe_proxy * np.ones(len(price))
        return pd.Series(equity_yield, index=price.index)
    
    def calculate_spread(self, equity_yield: pd.Series, 
                        bond_yield: pd.Series) -> pd.Series:
        """
        计算股债利差 = 股票盈利收益率 - 债券收益率
        """
        # 对齐
        common_idx = equity_yield.index.intersection(bond_yield.index)
        ey = equity_yield.loc[common_idx]
        by = bond_yield.loc[common_idx]
        
        spread = ey - by
        return spread
    
    def calculate_position_from_spread(self, spread: pd.Series) -> pd.Series:
        """
        根据利差计算目标仓位
        
        规则：
        - 利差 > 75%分位：100%仓位
        - 利差 50-75%分位：80%仓位
        - 利差 25-50%分位：50%仓位
        - 利差 < 25%分位：0%仓位
        """
        # 计算历史分位数（基于整个历史，不是滚动）
        quantile_75 = spread.quantile(self.exit_quantile)
        quantile_50 = spread.quantile(0.5)
        quantile_25 = spread.quantile(self.entry_quantile)
        
        position = pd.Series(0.0, index=spread.index)
        
        # 满仓
        position[spread >= quantile_75] = self.max_position
        # 标准仓位
        position[(spread >= quantile_50) & (spread < quantile_75)] = 0.8
        # 低仓位
        position[(spread >= quantile_25) & (spread < quantile_50)] = 0.5
        # 清仓
        position[spread < quantile_25] = self.min_position
        
        return position
    
    def generate(self, price_data: pd.DataFrame,
                 bond_yield: pd.Series = None,
                 pe_proxy: float = 15.0) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            price_data: 价格数据（含close列）
            bond_yield: 10年国债收益率序列（如果没有，用默认2.8%）
            pe_proxy: 默认PE倍数
            
        Returns:
            DataFrame with columns: date, close, spread, position, signal
        """
        close = price_data['close']
        
        # 计算股票盈利收益率
        equity_yield = self.calculate_equity_yield(close, pe_proxy)
        
        # 如果没有国债收益率，用默认2.8%
        if bond_yield is None:
            bond_yield = pd.Series(0.028, index=close.index)
        
        # 计算利差
        spread = self.calculate_spread(equity_yield, bond_yield)
        
        # 计算仓位
        position = self.calculate_position_from_spread(spread)
        
        # 生成信号：仓位变化
        signal = position.diff().fillna(0)
        signal[signal > 0] = 1   # 加仓
        signal[signal < 0] = -1  # 减仓
        
        result = pd.DataFrame({
            'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
            'close': close,
            'spread': spread,
            'position': position,
            'signal': signal,
        })
        
        return result.reset_index(drop=True)


class PEPercentileStrategy:
    """
    PE百分位择时策略
    基于指数PE历史百分位进行仓位管理
    
    原理：
    - PE百分位低 → 市场低估 → 高仓位
    - PE百分位高 → 市场高估 → 低仓位
    """
    
    def __init__(self, lookback: int = 252,
                 buy_threshold: float = 0.3,
                 sell_threshold: float = 0.7):
        self.lookback = lookback
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
    
    def calculate_pe_percentile(self, pe_history: pd.Series) -> pd.Series:
        """计算滚动PE百分位"""
        lb = min(self.lookback, len(pe_history) - 1)
        result = []
        for i in range(len(pe_history)):
            if i < lb:
                result.append(50.0)
            else:
                window = pe_history.iloc[i-lb:i]
                current = pe_history.iloc[i]
                pct = (window < current).mean() * 100
                result.append(pct)
        return pd.Series(result, index=pe_history.index)
    
    def generate(self, price_data: pd.DataFrame,
                 pe_history: pd.Series = None) -> pd.DataFrame:
        """
        生成信号
        
        Args:
            pe_history: PE历史序列（如果没有，用价格模拟）
        """
        close = price_data['close']
        
        if pe_history is None:
            # 用价格模拟PE：价格涨→PE高，价格跌→PE低
            # 假设初始PE=15，PE与价格成正比
            base_pe = 15.0
            base_price = close.iloc[0]
            pe_history = (close / base_price) * base_pe
        
        # 计算PE百分位
        pe_pct = self.calculate_pe_percentile(pe_history)
        
        # 生成仓位
        position = pd.Series(0.0, index=close.index)
        position[pe_pct < self.buy_threshold * 100] = 1.0   # 低估满仓
        position[(pe_pct >= self.buy_threshold * 100) & 
                 (pe_pct < self.sell_threshold * 100)] = 0.5  # 中等仓位
        position[pe_pct >= self.sell_threshold * 100] = 0.0  # 高估清仓
        
        # 生成交易信号
        signal = position.diff().fillna(0)
        signal[signal > 0] = 1
        signal[signal < 0] = -1
        
        return pd.DataFrame({
            'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
            'close': close,
            'pe': pe_history,
            'pe_percentile': pe_pct,
            'position': position,
            'signal': signal,
        })


class MultiFactorWithValuation:
    """
    多因子+估值择时综合策略
    
    组合多个因子：
    1. 估值因子（PE百分位/股债利差）
    2. 动量因子（20日/60日）
    3. 趋势因子（MA状态）
    
    最终仓位 = 加权组合
    """
    
    def __init__(self, 
                 valuation_weight: float = 0.4,
                 momentum_weight: float = 0.3,
                 trend_weight: float = 0.3):
        self.valuation_weight = valuation_weight
        self.momentum_weight = momentum_weight
        self.trend_weight = trend_weight
    
    def _zscore(self, s: pd.Series, lookback: int = 60) -> pd.Series:
        """Z-Score标准化"""
        mean = s.rolling(lookback, min_periods=20).mean()
        std = s.rolling(lookback, min_periods=20).std()
        return (s - mean) / (std + 1e-10)
    
    def generate(self, price_data: pd.DataFrame,
                 pe_history: pd.Series = None,
                 bond_yield: float = 0.028) -> pd.DataFrame:
        """
        生成综合信号
        """
        close = price_data['close']
        volume = price_data.get('volume', pd.Series(1, index=close.index))
        
        # 1. 估值因子
        if pe_history is None:
            base_pe = 15.0
            base_price = close.iloc[0]
            pe_history = (close / base_price) * base_pe
        
        pe_pct_strategy = PEPercentileStrategy()
        pe_pct = pe_pct_strategy.calculate_pe_percentile(pe_history)
        
        # 估值仓位：低估(低百分位)→高仓位
        val_position = pd.Series(0.0, index=close.index)
        val_position[pe_pct < 30] = 1.0
        val_position[(pe_pct >= 30) & (pe_pct < 70)] = 0.5
        val_position[pe_pct >= 70] = 0.0
        
        # 2. 动量因子
        momentum_20 = close.pct_change(20)
        momentum_60 = close.pct_change(60)
        mom_z = self._zscore(momentum_20)
        
        # 动量仓位：正动量→高仓位
        mom_position = pd.Series(0.0, index=close.index)
        mom_position[mom_z > 0] = 0.8
        mom_position[mom_z <= 0] = 0.2
        
        # 3. 趋势因子
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        
        trend_position = pd.Series(0.0, index=close.index)
        trend_position[close > ma20] = 0.7
        trend_position[close > ma20] = 0.7
        trend_position[(close <= ma20) | (ma20 < ma60)] = 0.3
        
        # 综合仓位
        combined_position = (
            val_position * self.valuation_weight +
            mom_position * self.momentum_weight +
            trend_position * self.trend_weight
        )
        
        # 限制在0-1之间
        combined_position = combined_position.clip(0, 1)
        
        # 生成信号
        signal = combined_position.diff().fillna(0)
        signal[signal > 0.1] = 1
        signal[signal < -0.1] = -1
        signal[(signal >= -0.1) & (signal <= 0.1)] = 0
        
        return pd.DataFrame({
            'date': price_data['date'] if 'date' in price_data.columns else price_data.index,
            'close': close,
            'pe_percentile': pe_pct,
            'val_position': val_position,
            'mom_position': mom_position,
            'trend_position': trend_position,
            'position': combined_position,
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
        """运行回测"""
        # 对齐
        sig = signals.copy()
        px = price_data.copy()
        
        if 'date' in sig.columns:
            sig = sig.set_index('date')
        if 'date' in px.columns:
            px = px.set_index('date')
        
        common_idx = sig.index.intersection(px.index)
        sig = sig.loc[common_idx]
        px = px.loc[common_idx]
        
        equity = self.initial_capital
        equity_curve = []
        position = 0
        entry_price = 0
        
        for i, date in enumerate(common_idx):
            target_pos = sig.loc[date, 'position']
            close = px.loc[date, 'close']
            
            # 调仓
            if target_pos != position:
                if position > 0:
                    # 平仓
                    ret = (close * (1 - self.slippage) - entry_price) / entry_price
                    equity *= (1 + ret)
                    equity *= (1 - self.commission)
                
                if target_pos > 0:
                    # 开仓
                    position = target_pos
                    entry_price = close * (1 + self.slippage)
                else:
                    position = 0
                    entry_price = 0
            
            # 记录权益
            if position > 0:
                current_equity = equity * (close / entry_price)
            else:
                current_equity = equity
            
            equity_curve.append({
                'date': date,
                'equity': current_equity,
                'position': position
            })
        
        equity_df = pd.DataFrame(equity_curve)
        
        # 买入持有基准
        buy_hold = (px['close'].iloc[-1] / px['close'].iloc[0] - 1) * 100
        
        # 策略收益
        strategy_return = (equity_df['equity'].iloc[-1] / self.initial_capital - 1) * 100
        
        # 统计
        returns = equity_df['equity'].pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak'] * 100
        max_dd = equity_df['drawdown'].min()
        
        return {
            'equity_curve': equity_df,
            'total_return': strategy_return,
            'benchmark': buy_hold,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
            'final_equity': equity_df['equity'].iloc[-1],
        }
