"""
多因子策略 v2
==================
整合三大类因子：
1. 技术因子：动量、波动率、成交量、趋势、RS、价格位置
2. 基本面因子：PE、PB、股息率（历史分位）
3. 情感因子：新闻情绪、资金流向

用法:
    from strategies.multi_factor import TripleFactorStrategy
    strat = TripleFactorStrategy()
    signals = strat.generate(price_data, fundamental_data, sentiment_data)
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, List


# ============ 因子计算 ============

def compute_technical_factors(df: pd.DataFrame) -> pd.DataFrame:
    """计算技术因子"""
    close = df["close"]
    volume = df["volume"]
    returns = close.pct_change()

    # 1. 动量因子：20日收益率
    momentum = close.pct_change(20)

    # 2. 波动率因子：20日收益标准差（负向，越低越好）
    volatility = returns.rolling(20).std()

    # 3. 成交量比：今日量/20日均量
    avg_vol = volume.rolling(20).mean()
    vol_ratio = volume / (avg_vol + 1e-10)

    # 4. MA金叉因子：(MA5-MA20)/MA20
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma_cross = (ma5 - ma20) / (ma20 + 1e-10)

    # 5. 趋势斜率：MA5相对60日MA的位置
    ma60 = close.rolling(60).mean()
    trend_slope = (ma5 - ma60) / (ma60 + 1e-10)

    # 6. 相对强弱：20日上涨天数比例
    up_days = (returns > 0).rolling(20).sum()
    rs = up_days / 20.0

    # 7. 价格位置：当前价在20日高低价的位置
    high20 = close.rolling(20).max()
    low20 = close.rolling(20).min()
    price_pos = (close - low20) / (high20 - low20 + 1e-10)

    # 8. 动量加速度：动量变化率
    mom_change = momentum.diff(5)

    return pd.DataFrame({
        "momentum": momentum,
        "volatility": volatility,
        "vol_ratio": vol_ratio,
        "ma_cross": ma_cross,
        "trend_slope": trend_slope,
        "rs": rs,
        "price_pos": price_pos,
        "mom_accel": mom_change,
    }, index=df.index)


def compute_fundamental_factors(fund_df: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """
    计算基本面因子（基于历史分位）

    Args:
        fund_df: DataFrame with date, pe, pb, dividend_rate
        lookback: 计算分位的窗口
    """
    if fund_df.empty:
        return pd.DataFrame()

    result = pd.DataFrame(index=fund_df.index)

    for col in ["pe", "pb", "dividend_rate"]:
        if col in fund_df.columns:
            # 滚动历史分位：当前值在过去N天中的位置（0~1）
            vals = fund_df[col].values
            n = len(vals)
            pctile = np.zeros(n)
            for i in range(n):
                if i < lookback:
                    pctile[i] = 0.5
                else:
                    window = vals[i - lookback:i + 1]
                    pctile[i] = (vals[i] <= window).sum() / len(window)

            result[col + "_pct"] = pctile

    # PE倒数 = 盈利收益率（E/P）
    if "pe" in fund_df.columns:
        ep = 1.0 / (fund_df["pe"].values + 1e-10)
        # 盈利收益率相对历史分位
        ep_pct = np.zeros(len(ep))
        for i in range(len(ep)):
            if i < lookback:
                ep_pct[i] = 0.5
            else:
                window = ep[i - lookback:i + 1]
                ep_pct[i] = (ep[i] <= window).sum() / len(window)
        result["ep_pct"] = ep_pct

    return result


def compute_sentiment_factors(sentiment_df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    计算情感因子

    Args:
        sentiment_df: DataFrame with date, sentiment_score, fund_flow
    """
    if sentiment_df.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([]))

    result = pd.DataFrame(index=sentiment_df.index)

    if "sentiment_score" in sentiment_df.columns:
        # 滚动平均情感得分
        result["sentiment_ma"] = sentiment_df["sentiment_score"].rolling(lookback).mean()
        # 情感变化
        result["sentiment_chg"] = sentiment_df["sentiment_score"].diff(lookback)

    if "fund_flow" in sentiment_df.columns:
        # 资金流向的5日移动平均
        result["fund_flow_ma"] = sentiment_df["fund_flow"].rolling(lookback).mean()
        # 资金流向为正
        result["fund_flow_pos"] = (sentiment_df["fund_flow"] > 0).astype(float)

    return result


def zscore(series: pd.Series, lookback: int = 60) -> pd.Series:
    """滚动Z-Score标准化"""
    ma = series.rolling(lookback, min_periods=20).mean()
    std = series.rolling(lookback, min_periods=20).std()
    return (series - ma) / (std + 1e-10)


# ============ 三因子策略 ============

class TripleFactorStrategy:
    """
    三因子综合评分策略

    因子配置（可通过构造函数调整权重）:
    - 技术因子: 动量(20%) + 波动率(10%) + 成交量(10%) + 趋势(20%) + RS(10%)
    - 基本面因子: PE分位(15%) + 股息率分位(15%)
    - 情感因子: 新闻情绪(10%) + 资金流向(10%)

    择时规则:
    - 综合评分 > 0.6分位 → 持仓
    - 综合评分 < 0.4分位 → 空仓
    - 中间 → 持有50%
    """

    def __init__(
        self,
        tech_weight: float = 0.50,
        fund_weight: float = 0.30,
        sent_weight: float = 0.20,
        rebalance_days: int = 5,
    ):
        self.tech_weight = tech_weight
        self.fund_weight = fund_weight
        self.sent_weight = sent_weight
        self.rebalance_days = rebalance_days

    def _score_technical(self, tech: pd.DataFrame) -> pd.Series:
        """技术因子综合评分"""
        score = pd.Series(0.0, index=tech.index)

        # 动量：越高越好
        score += zscore(tech["momentum"]).clip(-3, 3)

        # 波动率：越低越好（负向）
        score -= zscore(tech["volatility"]).clip(-3, 3)

        # 成交量：越高越好
        score += zscore(tech["vol_ratio"]).clip(-3, 3)

        # MA金叉：越高越好
        score += zscore(tech["ma_cross"]).clip(-3, 3)

        # 趋势：越高越好
        score += zscore(tech["trend_slope"]).clip(-3, 3)

        # RS：越高越好
        score += zscore(tech["rs"]).clip(-3, 3)

        # 价格位置：0.3~0.7之间最好（不高不低）
        pp_penalty = -(tech["price_pos"] - 0.5).abs()
        score += zscore(pp_penalty).clip(-3, 3)

        return score

    def _score_fundamental(self, fund: pd.DataFrame) -> pd.Series:
        """基本面因子综合评分"""
        score = pd.Series(0.0, index=fund.index)

        if "pe_pct" in fund.columns:
            # PE分位越低越好（便宜）
            score -= zscore(fund["pe_pct"]).clip(-3, 3)

        if "dividend_rate_pct" in fund.columns:
            # 股息率分位越高越好
            score += zscore(fund["dividend_rate_pct"]).clip(-3, 3)

        if "ep_pct" in fund.columns:
            # 盈利收益率分位越高越好
            score += zscore(fund["ep_pct"]).clip(-3, 3)

        return score

    def _score_sentiment(self, sent: pd.DataFrame) -> pd.Series:
        """情感因子综合评分"""
        score = pd.Series(0.0, index=sent.index)

        if "sentiment_ma" in sent.columns:
            score += zscore(sent["sentiment_ma"]).clip(-3, 3)

        if "fund_flow_ma" in sent.columns:
            score += zscore(sent["fund_flow_ma"]).clip(-3, 3)

        return score

    def generate(
        self,
        price_data: pd.DataFrame,
        fund_data: Optional[pd.DataFrame] = None,
        sentiment_data: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            price_data: OHLCV数据
            fund_data: 基本面数据 (date, pe, pb, dividend_rate)
            sentiment_data: 情感数据 (date, sentiment_score, fund_flow)
        """
        # Step 1: 技术因子
        tech = compute_technical_factors(price_data)
        tech_score = self._score_technical(tech)

        # Step 2: 基本面因子
        if fund_data is not None and not fund_data.empty:
            fund = compute_fundamental_factors(fund_data)
            fund_score = self._score_fundamental(fund)
        else:
            fund_score = pd.Series(0.0, index=price_data.index)

        # Step 3: 情感因子
        if sentiment_data is not None and not sentiment_data.empty:
            sent = compute_sentiment_factors(sentiment_data)
            sent_score = self._score_sentiment(sent)
        else:
            sent_score = pd.Series(0.0, index=price_data.index)

        # Step 4: 对齐所有评分到价格数据的索引
        idx = price_data.index
        tech_score = tech_score.reindex(idx, fill_value=0)
        fund_score = fund_score.reindex(idx, fill_value=0)
        sent_score = sent_score.reindex(idx, fill_value=0)

        # Step 5: 加权综合评分
        total_score = (
            self.tech_weight * tech_score
            + self.fund_weight * fund_score
            + self.sent_weight * sent_score
        )

        # Step 6: 生成信号
        signals = pd.DataFrame(index=idx)
        signals["date"] = price_data["date"].values if "date" in price_data.columns else idx
        signals["close"] = price_data["close"].values
        signals["tech_score"] = tech_score.values
        signals["fund_score"] = fund_score.values
        signals["sent_score"] = sent_score.values
        signals["total_score"] = total_score.values

        # 仓位决策（基于评分的滚动分位）
        position = pd.Series(0.0, index=idx)
        lookback = 60
        n = len(total_score)

        for i in range(n):
            if i < lookback + 5:
                continue
            window = total_score.iloc[i - lookback:i]
            p60 = window.quantile(0.6)
            p40 = window.quantile(0.4)
            score = total_score.iloc[i]

            # 额外条件：动量必须为正（避免逆势抄底）
            mom_ok = tech["momentum"].iloc[i] > -0.05 if i < len(tech) else True

            if score > p60 and mom_ok:
                position.iloc[i] = 1.0
            elif score < p40:
                position.iloc[i] = 0.0
            else:
                position.iloc[i] = 0.5  # 中性持有50%

        signals["position"] = position.values
        signals["signal"] = position.diff().fillna(0)
        signals["signal"] = signals["signal"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        return signals.reset_index(drop=True)


# ============ 简化版：纯技术 + 动量择时 ============

class MomentumFactorStrategy:
    """
    动量因子策略（纯技术，无基本面/情感依赖）

    核心：20日动量 + 波动率调整 + 趋势过滤

    用法:
        strat = MomentumFactorStrategy()
        signals = strat.generate(price_data)
    """

    def __init__(self, mom_window: int = 20, vol_window: int = 20):
        self.mom_window = mom_window
        self.vol_window = vol_window

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        close = data["close"]
        returns = close.pct_change()

        # 动量
        momentum = close.pct_change(self.mom_window)

        # 波动率（年化）
        vol = returns.rolling(self.vol_window).std() * np.sqrt(252)

        # 风险调整动量：动量/波动率
        risk_adj_mom = momentum / (vol + 1e-10)

        # 趋势过滤：MA60向上
        ma60 = close.rolling(60).mean()
        trend_up = close > ma60

        # 波动率过滤：波动率低于历史中位数（避免高波动期）
        vol_median = vol.rolling(252).median()
        low_vol = vol < vol_median

        # 综合信号
        score = pd.Series(0.0, index=data.index)
        score += zscore(momentum).clip(-3, 3) * 0.5
        score += zscore(risk_adj_mom).clip(-3, 3) * 0.5

        # 仓位
        position = pd.Series(0.0, index=data.index)
        lookback = 60

        for i in range(lookback, len(score)):
            p60 = score.iloc[i - lookback:i].quantile(0.6)
            cond = (
                (score.iloc[i] > p60)
                & trend_up.iloc[i]
                & low_vol.iloc[i]
            )
            position.iloc[i] = 1.0 if cond else 0.0

        signal = position.diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        result = pd.DataFrame({
            "date": data["date"].values if "date" in data.columns else data.index,
            "close": close.values,
            "momentum": momentum.values,
            "volatility": vol.values,
            "risk_adj_mom": risk_adj_mom.values,
            "trend_up": trend_up.values.astype(float),
            "low_vol": low_vol.values.astype(float),
            "score": score.values,
            "position": position.values,
            "signal": signal.values,
        })

        return result.reset_index(drop=True)


# ============ 快速回测器 ============

def quick_backtest(
    price_data: pd.DataFrame,
    signals: pd.DataFrame,
    initial_capital: float = 100_000,
    commission: float = 0.0003,
    slippage: float = 0.0001,
) -> dict:
    """快速回测"""

    # 对齐
    sig = signals.copy().reset_index(drop=True)
    px = price_data.copy().reset_index(drop=True)

    if "date" in sig.columns and "date" in px.columns:
        common = set(sig["date"]) & set(px["date"])
        sig = sig[sig["date"].isin(common)].reset_index(drop=True)
        px = px[px["date"].isin(common)].reset_index(drop=True)

    equity = initial_capital
    position = 0
    entry_price = 0
    equity_curve = []
    trades = []

    for i in range(len(sig)):
        close = px.at[i, "close"]
        date = px.at[i, "date"] if "date" in px.columns else i
        target_pos = sig.at[i, "position"]

        # 交易
        if target_pos > position and position == 0:  # 买入
            cost = equity * (1 - commission - slippage)
            position = 1
            entry_price = close * (1 + slippage)
            equity = cost

        elif target_pos < position and position > 0:  # 卖出
            proceeds = equity * (close / entry_price) * (1 - commission - slippage)
            pnl = proceeds - equity
            equity = proceeds
            trades.append({"date": date, "pnl": pnl, "return": pnl / initial_capital})
            position = 0
            entry_price = 0

        # 权益
        if position > 0:
            cur_equity = equity * (close / entry_price)
        else:
            cur_equity = equity

        equity_curve.append({"date": date, "equity": cur_equity, "position": position})

    eq_df = pd.DataFrame(equity_curve)
    buyhold = (px["close"].iloc[-1] / px["close"].iloc[0] - 1) * 100
    strat_ret = (eq_df["equity"].iloc[-1] / initial_capital - 1) * 100

    returns = eq_df["equity"].pct_change().dropna()
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    eq_df["peak"] = eq_df["equity"].cummax()
    eq_df["dd"] = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"]
    max_dd = eq_df["dd"].min() * 100

    return {
        "equity_curve": eq_df,
        "trades": pd.DataFrame(trades),
        "total_return": strat_ret,
        "benchmark": buyhold,
        "excess": strat_ret - buyhold,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "n_trades": len(trades),
        "final_equity": eq_df["equity"].iloc[-1],
    }
