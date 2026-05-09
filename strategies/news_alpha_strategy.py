"""
strategies/news_alpha_strategy.py
==================================
信息alpha策略 — 新闻+资金流向驱动

核心逻辑:
  新闻情感(领先1-3天) + 资金流向 → 信号 → 交易

与动量/趋势策略的区别:
  - 动量/趋势: 追涨杀跌（滞后）
  - 信息alpha: 捕捉信息差（领先）

信号阈值:
  - composite_score > 0.62 → buy
  - composite_score < 0.38 → sell
  - else → hold
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Tuple
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from data.news_sentiment import (
    get_info_alpha, get_market_news, lexicon_sentiment,
    batch_sentiment, get_fund_flow, analyze_fund_flow
)
from strategies.base import Strategy


class NewsAlphaStrategy(Strategy):
    """
    信息alpha策略

    参数:
        threshold_high: 买入阈值 (默认0.62)
        threshold_low: 卖出阈值 (默认0.38)
        lookback: 资金流向回顾天数 (默认5)
        use_lexicon: 是否使用A股词典修正 (默认True)
        rebalance_freq: 调仓频率 (默认'1d')
    """

    def __init__(
        self,
        threshold_high: float = 0.62,
        threshold_low: float = 0.38,
        lookback: int = 5,
        use_lexicon: bool = True,
        rebalance_freq: str = '1d',
        name: str = "NewsAlpha"
    ):
        self.threshold_high = threshold_high
        self.threshold_low = threshold_low
        self.lookback = lookback
        self.use_lexicon = use_lexicon
        self.rebalance_freq = rebalance_freq
        self.name = name
        self.last_signal = None
        self.last_rebalance_date = None

    def generate(self, df: pd.DataFrame, sec_code: str = None) -> pd.DataFrame:
        """
        生成交易信号

        注意: df是历史价格数据，这里叠加新闻alpha信号
        真实使用时需要在每天收盘后获取当日news_alpha信号
        """
        if df.empty:
            return pd.DataFrame()

        result = df.copy()
        result['signal'] = 'hold'
        result['news_score'] = np.nan
        result['fund_flow_score'] = np.nan
        result['composite_score'] = np.nan
        result['signal_reason'] = ''

        # 用最近一天的info_alpha作为当前信号（用于回测最后一天）
        if sec_code:
            try:
                info = get_info_alpha(sec_code)
                current_score = info['composite_score']
                result.iloc[-1, result.columns.get_loc('composite_score')] = current_score
                result.iloc[-1, result.columns.get_loc('news_score')] = info['news_sentiment']
                result.iloc[-1, result.columns.get_loc('fund_flow_score')] = info['fund_flow_score']

                if current_score > self.threshold_high:
                    result.iloc[-1, result.columns.get_loc('signal')] = 'buy'
                    result.iloc[-1, result.columns.get_loc('signal_reason')] = f"alpha={current_score:.2f}>0.62"
                elif current_score < self.threshold_low:
                    result.iloc[-1, result.columns.get_loc('signal')] = 'sell'
                    result.iloc[-1, result.columns.get_loc('signal_reason')] = f"alpha={current_score:.2f}<0.38"
            except Exception as e:
                print(f"  ⚠️ get_info_alpha错误: {e}")

        return result.reset_index(drop=True)

    def get_current_signal(self, sec_code: str) -> dict:
        """实时获取当前信号（用于盘中决策）"""
        return get_info_alpha(sec_code)


class NewsAlphaBacktester:
    """
    信息alpha策略回测器

    模拟方式:
    - 假设每天收盘后获取当日news_alpha信号，T+1开盘执行
    - 用历史资金流数据模拟资金信号

    ⚠️ 注意: 新闻情感无法历史回测，只能用当日信号做模拟交易
    """

    def __init__(self, initial_capital: float = 1000000, threshold_high: float = 0.62, threshold_low: float = 0.38):
        self.initial_capital = initial_capital
        self.threshold_high = threshold_high
        self.threshold_low = threshold_low
        self.cash = initial_capital
        self.position = 0
        self.trades = []
        self.portfolio_value = [initial_capital]

    def run(self, df: pd.DataFrame, sec_code: str, max_position_pct: float = 0.95) -> dict:
        """
        回测news_alpha策略

        ⚠️ 限制: 新闻情感只能获取当前值，无法在历史回测中真实模拟
        这里用资金流向的历史数据来模拟信号

        df: 价格数据（含成交量）
        """
        if df.empty:
            return {}

        df = df.copy()
        df['signal'] = 'hold'

        # 用资金流向计算历史信号
        flow_df = get_fund_flow(sec_code)
        if not flow_df.empty:
            flow_analysis = analyze_fund_flow(flow_df, lookback=5)
            latest_flow_signal = flow_analysis['signal']
            latest_flow_score = flow_analysis['score']

            # 用资金得分作为今日信号
            last_date = df['date'].iloc[-1] if 'date' in df.columns else df.index[-1]
            if last_date in df['date'].values if 'date' in df.columns else True:
                score_col = 'composite_score'
                if score_col not in df.columns:
                    df[score_col] = np.nan

                # 用资金得分填充最近一天
                flow_score = latest_flow_score
                if latest_flow_signal == 'bullish':
                    score = 0.7
                elif latest_flow_signal == 'bearish':
                    score = 0.3
                else:
                    score = 0.5

                # 对齐日期
                try:
                    date_str = flow_df['日期'].iloc[-1].strftime('%Y-%m-%d')
                    mask = df['date'].astype(str).str[:10] == date_str if 'date' in df.columns else pd.Series([True] * len(df))
                    if mask.sum() > 0:
                        df.loc[mask, score_col] = flow_score
                        df.loc[mask, 'signal'] = 'buy' if flow_score > 0.62 else ('sell' if flow_score < 0.38 else 'hold')
                except:
                    pass

        return self._backtest_loop(df, sec_code)

    def _backtest_loop(self, df: pd.DataFrame, sec_code: str) -> dict:
        """核心回测循环"""
        self.cash = self.initial_capital
        self.position = 0
        self.trades = []
        self.portfolio_value = []

        for i in range(len(df)):
            row = df.iloc[i]
            price = row['close']
            date = row.get('date', i)

            # 当前组合价值
            portfolio_value = self.cash + self.position * price
            self.portfolio_value.append({'date': date, 'value': portfolio_value})

            signal = row.get('signal', 'hold')
            score = row.get('composite_score', 0.5)

            # 交易逻辑
            if signal == 'buy' and self.position == 0:
                # 全仓买入
                shares = int(self.cash * 0.95 / price)
                cost = shares * price
                self.cash -= cost
                self.position = shares
                self.trades.append({
                    'date': date, 'action': 'buy', 'price': price,
                    'shares': shares, 'cost': cost, 'reason': f'score={score:.2f}'
                })
            elif signal == 'sell' and self.position > 0:
                # 清仓
                proceeds = self.position * price
                self.cash += proceeds
                self.trades.append({
                    'date': date, 'action': 'sell', 'price': price,
                    'shares': self.position, 'proceeds': proceeds, 'reason': f'score={score:.2f}'
                })
                self.position = 0

        # 最终价值
        final_value = self.cash + self.position * df.iloc[-1]['close']
        returns = (final_value - self.initial_capital) / self.initial_capital * 100

        return {
            'returns': returns,
            'final_value': final_value,
            'total_trades': len(self.trades),
            'trades': self.trades,
            'portfolio_value': pd.DataFrame(self.portfolio_value)
        }


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '.')
    from data.cache import load_etf_data

    print("=" * 60)
    print("NewsAlpha策略 — 实时信号")
    print("=" * 60)

    test_codes = ['510300', '510500', '159915']
    results = []

    for code in test_codes:
        print(f"\n📊 {code}:")
        info = get_info_alpha(code)
        print(f"   新闻情感: {info['news_sentiment']:.2f}")
        print(f"   资金信号: {info['fund_flow_signal']} (得分: {info['fund_flow_score']:.2f})")
        print(f"   综合得分: {info['composite_score']:.2f}")
        print(f"   → 操作: {info['action']} ({info['confidence']:.0f}%置信度)")
        if info['news_summary']:
            print(f"   最新: {info['news_summary']}")
        results.append(info)

    print("\n" + "=" * 60)
    print("横向对比")
    print("=" * 60)
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('composite_score', ascending=False)
    print(df_results[['sec_code', 'composite_score', 'action', 'fund_flow_signal']].to_string(index=False))
