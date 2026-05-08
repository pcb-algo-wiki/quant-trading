"""
多因子选股策略
原理：结合多个技术因子（动量、波动率、成交量异常、趋势）构建综合评分
选评分最高的ETF买入，定期再平衡

适合ETF: 沪深300(510300)、中证500(510500)、创业板(159915)

用法:
    from strategies.multi_factor import MultiFactorStrategy
    strategy = MultiFactorStrategy(n_top=1, rebalance_days=5)
    signals = strategy.generate(data)
"""

import numpy as np
import pandas as pd
from typing import List, Dict


class MultiFactorStrategy:
    """
    多因子评分策略
    
    因子（全部从价量数据构造，无需基本面）：
    1. 动量因子 (Momentum): 20日收益率，越高越好
    2. 波动率因子 (Volatility): 20日收益标准差的倒数，越低越好
    3. 成交量因子 (Volume): 今日量/20日均量，越高说明资金关注
    4. 趋势因子 (Trend): MA5/MA20斜率，越陡峭越好
    5. 相对强弱 (RS): 20日涨跌天数比例
    
    综合评分：各因子Z-Score等权相加
    """
    
    def __init__(self, momentum_window: int = 20,
                 vol_window: int = 20,
                 volume_window: int = 20,
                 trend_window: int = 20,
                 n_top: int = 1,
                 rebalance_days: int = 5):
        self.momentum_window = momentum_window
        self.vol_window = vol_window
        self.volume_window = volume_window
        self.trend_window = trend_window
        self.n_top = n_top  # 每次选前n只
        self.rebalance_days = rebalance_days
    
    def _compute_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有因子"""
        close = df['close']
        volume = df['volume']
        
        # 1. 动量因子：N日收益率
        momentum = close.pct_change(self.momentum_window)
        
        # 2. 波动率因子：N日收益标准差的倒数
        returns = close.pct_change()
        volatility = returns.rolling(self.vol_window).std()
        vol_factor = 1 / (volatility + 1e-10)
        
        # 3. 成交量因子：今日量/均量
        avg_volume = volume.rolling(self.volume_window).mean()
        vol_ratio = volume / (avg_volume + 1e-10)
        
        # 4. 趋势因子：MA5斜率
        ma5 = close.rolling(5).mean()
        ma20 = close.rolling(20).mean()
        trend_slope = (ma5 / ma5.shift(self.trend_window) - 1)
        ma_cross_factor = (ma5 - ma20) / (ma20 + 1e-10)
        
        # 5. 相对强弱：上涨天数比例
        up_days = (returns > 0).rolling(self.momentum_window).sum()
        rs_factor = up_days / self.momentum_window
        
        # 6.  价格位置：当前价在N日高低价的位置
        high_n = close.rolling(self.momentum_window).max()
        low_n = close.rolling(self.momentum_window).min()
        price_position = (close - low_n) / (high_n - low_n + 1e-10)
        
        # 组合DataFrame
        factors = pd.DataFrame({
            'momentum': momentum,
            'vol_factor': vol_factor,
            'vol_ratio': vol_ratio,
            'trend_slope': trend_slope,
            'ma_cross': ma_cross_factor,
            'rs': rs_factor,
            'price_pos': price_position,
        }, index=df.index)
        
        return factors
    
    def _zscore(self, s: pd.Series, lookback: int = 60) -> pd.Series:
        """滚动Z-Score标准化"""
        mean = s.rolling(lookback, min_periods=20).mean()
        std = s.rolling(lookback, min_periods=20).std()
        return (s - mean) / (std + 1e-10)
    
    def _score_factors(self, factors: pd.DataFrame) -> pd.Series:
        """将各因子标准化后等权相加"""
        scored = pd.Series(0.0, index=factors.index)
        
        # 动量：越高越好（正相关）
        m = self._zscore(factors['momentum'])
        scored += m
        
        # 波动率：越低越好（负相关）
        v = self._zscore(factors['vol_factor'])
        scored -= v
        
        # 成交量比：越高越好（正相关）
        vr = self._zscore(factors['vol_ratio'])
        scored += vr
        
        # 趋势斜率：越高越好
        ts = self._zscore(factors['trend_slope'])
        scored += ts
        
        # MA金叉：MA5>MA20越好
        mc = self._zscore(factors['ma_cross'])
        scored += mc
        
        # 相对强弱：越高越好
        rs = self._zscore(factors['rs'])
        scored += rs
        
        # 价格位置：中间偏上最好（不要追高）
        # 使用距离0.5的绝对值，越接近0.5越好（不高不低）
        pp = -(factors['price_pos'] - 0.5).abs()
        pp_z = self._zscore(pp)
        scored += pp_z
        
        return scored
    
    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 单只ETF的OHLC数据
            
        Returns:
            DataFrame with columns: signal, score, position_size
        """
        # 计算因子
        factors = self._compute_factors(data)
        
        # 计算综合评分
        score = self._score_factors(factors)
        
        # 生成信号
        signals = pd.DataFrame(index=data.index)
        signals['date'] = data['date'] if 'date' in data.columns else data.index
        signals['close'] = data['close']
        signals['score'] = score
        signals['signal'] = 0  # 0=空仓, 1=持仓
        
        # 定期再平衡：每rebalance_days天检查一次
        n = len(signals)
        position = 0
        
        for i in range(n):
            # 每天检查是否需要调仓
            if i % self.rebalance_days == 0 and i >= 60:
                # 取过去60天评分最高的窗口
                lookback = 60
                if i >= lookback:
                    window_scores = score.iloc[i-lookback:i]
                    current_score = score.iloc[i]
                    
                    # 评分超过历史60%分位且动量为正才入场
                    threshold = window_scores.quantile(0.6)
                    if current_score > threshold and factors['momentum'].iloc[i] > 0:
                        position = 1
                    else:
                        position = 0
            
            signals.iloc[i, signals.columns.get_loc('signal')] = position
        
        return signals.reset_index(drop=True)


class MultiFactorBacktester:
    """
    多因子策略回测引擎
    """
    
    def __init__(self, initial_capital: float = 100000.0,
                 commission: float = 0.0003,
                 slippage: float = 0.0001):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
    
    def run(self, signals: pd.DataFrame, prices: pd.DataFrame,
            etf_name: str = '') -> dict:
        """
        运行单只ETF回测
        """
        # 对齐
        common_idx = signals.index.intersection(prices.index)
        sig = signals.loc[common_idx].reset_index(drop=True)
        px = prices.loc[common_idx].reset_index(drop=True)
        
        equity = self.initial_capital
        equity_curve = []
        trades = []
        position = 0
        entry_price = 0
        entry_date = ''
        
        for i in range(len(sig)):
            current_signal = sig['signal'].iloc[i]
            close = px['close'].iloc[i]
            date = px['date'].iloc[i] if 'date' in px.columns else common_idx[i]
            
            # 入场
            if current_signal == 1 and position == 0:
                position = 1
                entry_price = close * (1 + self.slippage)
                entry_date = date
            
            # 出场
            elif current_signal == 0 and position == 1:
                exit_price = close * (1 - self.slippage)
                pnl = (exit_price - entry_price) / entry_price * equity
                cost = equity * self.commission
                net_pnl = pnl - cost
                equity += net_pnl
                
                trades.append({
                    'date': date,
                    'entry_date': entry_date,
                    'type': 'long',
                    'pnl': net_pnl,
                    'return': net_pnl / self.initial_capital * 100,
                    'equity': equity
                })
                position = 0
            
            equity_curve.append({
                'date': date,
                'equity': equity,
                'position': position
            })
        
        # 平仓
        if position == 1:
            close = px['close'].iloc[-1]
            date = px['date'].iloc[-1] if 'date' in px.columns else common_idx[-1]
            exit_price = close * (1 - self.slippage)
            pnl = (exit_price - entry_price) / entry_price * equity
            cost = equity * self.commission
            net_pnl = pnl - cost
            equity += net_pnl
            trades.append({
                'date': date,
                'entry_date': entry_date,
                'type': 'close',
                'pnl': net_pnl,
                'return': net_pnl / self.initial_capital * 100,
                'equity': equity
            })
        
        equity_df = pd.DataFrame(equity_curve)
        
        # 基准
        buy_hold = (px['close'].iloc[-1] / px['close'].iloc[0] - 1) * 100
        
        return {
            'equity_curve': equity_df,
            'trades': pd.DataFrame(trades),
            'total_return': (equity / self.initial_capital - 1) * 100,
            'benchmark': buy_hold,
            'n_trades': len(trades),
            'final_equity': equity,
            'etf_name': etf_name,
        }


class CrossSectionalPortfolio:
    """
    跨截面多因子组合
    同时分析多只ETF，选评分最高的持有
    """
    
    def __init__(self, etf_data: dict, strategy: MultiFactorStrategy,
                 initial_capital: float = 100000.0):
        self.etf_data = etf_data  # {name: dataframe}
        self.strategy = strategy
        self.initial_capital = initial_capital
    
    def run(self) -> dict:
        """运行组合回测"""
        # Step 1: 计算每只ETF的因子和评分
        all_factors = {}
        all_signals = {}
        
        for name, df in self.etf_data.items():
            factors = self.strategy._compute_factors(df)
            score = self.strategy._score_factors(factors)
            signals = self.strategy.generate(df)
            
            all_factors[name] = factors
            all_signals[name] = signals
        
        # Step 2: 每日跨截面评分，选择评分最高的ETF
        # 对齐日期
        common_dates = None
        for df in self.etf_data.values():
            dates = set(df['date']) if 'date' in df.columns else set(df.index)
            if common_dates is None:
                common_dates = dates
            else:
                common_dates = common_dates.intersection(dates)
        
        common_dates = sorted(list(common_dates))
        
        # 每日选择评分最高的ETF
        daily_selection = []
        for i, date in enumerate(common_dates):
            if i < 60:  # 预热期
                daily_selection.append(None)
                continue
            
            scores = {}
            for name, df in self.etf_data.items():
                df_dates = df['date'] if 'date' in df.columns else df.index
                if date in set(df_dates):
                    idx = df[df['date'] == date].index[0] if 'date' in df.columns else date
                    score = all_signals[name].loc[all_signals[name]['date'] == date, 'score'].values
                    if len(score) > 0:
                        scores[name] = score[0]
            
            if scores:
                best_etf = max(scores, key=scores.get)
                daily_selection.append(best_etf)
            else:
                daily_selection.append(None)
        
        # Step 3: 回测 - 持有评分最高的ETF
        equity = self.initial_capital
        equity_curve = []
        current_holding = None
        entry_price = 0
        entry_date = None
        
        for i, date in enumerate(common_dates):
            # 获取当日收盘价
            prices = {}
            for name, df in self.etf_data.items():
                df_dates = df['date'] if 'date' in df.columns else df.index
                if date in set(df_dates):
                    row = df[df['date'] == date]
                    if len(row) > 0:
                        prices[name] = row['close'].values[0]
            
            if not prices or daily_selection[i] is None:
                equity_curve.append({'date': date, 'equity': equity, 'holding': None})
                continue
            
            best_etf = daily_selection[i]
            current_price = prices.get(best_etf)
            
            if current_holding is None:
                # 入场
                if best_etf and current_price:
                    current_holding = best_etf
                    entry_price = current_price
                    entry_date = date
            else:
                # 持仓中
                if best_etf != current_holding or i % self.strategy.rebalance_days == 0:
                    # 换仓或再平衡
                    if current_holding in prices:
                        exit_price = prices[current_holding]
                        ret = (exit_price - entry_price) / entry_price
                        equity *= (1 + ret)
                    
                    if best_etf and best_etf in prices:
                        current_holding = best_etf
                        entry_price = prices[best_etf]
                        entry_date = date
                    else:
                        current_holding = None
            
            holding_name = current_holding if current_holding else 'none'
            equity_curve.append({'date': date, 'equity': equity, 'holding': holding_name})
        
        # 计算基准
        if common_dates:
            first_date = common_dates[0]
            last_date = common_dates[-1]
            
            benchmark_returns = []
            for name, df in self.etf_data.items():
                first_price = df[df['date'] == first_date]['close'].values
                last_price = df[df['date'] == last_date]['close'].values
                if len(first_price) > 0 and len(last_price) > 0:
                    ret = (last_price[0] / first_price[0] - 1) * 100
                    benchmark_returns.append(ret)
            
            benchmark = np.mean(benchmark_returns) if benchmark_returns else 0
        else:
            benchmark = 0
        
        equity_df = pd.DataFrame(equity_curve)
        
        return {
            'equity_curve': equity_df,
            'total_return': (equity / self.initial_capital - 1) * 100,
            'benchmark': benchmark,
            'final_equity': equity,
            'daily_selection': dict(zip(common_dates, daily_selection)),
        }
