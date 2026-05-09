"""
多策略集成模块
==============

核心思路：没有万能策略，不同市场环境适合不同策略。
通过动态权重分配，让系统自动适应。

策略族：
  1. EnsembleStrategy      - 静态等权平均（baseline）
  2. AdaptiveEnsemble      - 基于滚动夏普动态调权重
  3. VotingEnsemble        - 多空信号投票
  4. RegimeSwitchingEnsemble - 根据市场状态自适应切换策略组合

用法:
    from strategies.ensemble import AdaptiveEnsemble
    strat = AdaptiveEnsemble()
    signals = strat.generate(price_data)
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Tuple
from strategies.multi_factor import TripleFactorStrategy, MomentumFactorStrategy
from strategies.stock_bond_rotation import StockBondRotationStrategy
from strategies.trend import MA_Cross


def _compute_recent_sharpe(equity_curve: pd.Series, lookback: int = 60) -> float:
    """计算最近N天的夏普比率"""
    if len(equity_curve) < lookback:
        lookback = len(equity_curve)
    if lookback < 5:
        return 0.0
    returns = equity_curve.tail(lookback).pct_change().dropna()
    if returns.std() == 0:
        return 0.0
    return returns.mean() / returns.std() * np.sqrt(252)


def _backtest_fast(
    price_data: pd.DataFrame,
    signals: pd.DataFrame,
    initial_capital: float = 100_000,
    commission: float = 0.0003,
) -> Tuple[pd.DataFrame, float, float]:
    """
    快速回测，返回(equity_curve, total_return, sharpe)
    """
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

    for i in range(len(sig)):
        close = px.at[i, "close"]
        date = px.at[i, "date"] if "date" in px.columns else i
        target_pos = sig.at[i, "position"]
        binary_target = 1 if target_pos > 0.5 else 0

        if binary_target == 1 and position == 0:
            cost = equity * (1 - commission)
            position = 1
            entry_price = close
            equity = cost
        elif binary_target == 0 and position == 1:
            proceeds = equity * (close / entry_price) * (1 - commission)
            equity = proceeds
            position = 0
            entry_price = 0

        if position > 0:
            cur_equity = equity * (close / entry_price)
        else:
            cur_equity = equity

        equity_curve.append({"date": date, "equity": cur_equity})

    eq_df = pd.DataFrame(equity_curve)
    total_return = (eq_df["equity"].iloc[-1] / initial_capital - 1) * 100
    returns = eq_df["equity"].pct_change().dropna()
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    return eq_df, total_return, sharpe


# ============ 基础集成策略 ============

class EnsembleStrategy:
    """
    多策略等权平均集成

    组合：TripleFactor + MomentumFactor + StockBondRotation
    等权平均三者的position，再二值化

    用法:
        strat = EnsembleStrategy()
        signals = strat.generate(price_data)
    """

    def __init__(
        self,
        strategies: Optional[List] = None,
        weights: Optional[List[float]] = None,
        threshold: float = 0.5,
    ):
        """
        Args:
            strategies: 策略列表，默认[TripleFactor, MomentumFactor, StockBondRotation]
            weights: 各策略权重，默认等权
            threshold: 集成position二值化阈值
        """
        if strategies is None:
            self.strategies = [
                TripleFactorStrategy(),
                MomentumFactorStrategy(),
            ]
        else:
            self.strategies = strategies

        n = len(self.strategies)
        self.weights = weights if weights else [1.0] * n
        self.threshold = threshold

    def generate(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        # 收集各策略的position
        positions = []
        for strat in self.strategies:
            sig = strat.generate(data, **kwargs)
            if "position" in sig.columns:
                positions.append(sig["position"].values)
            else:
                positions.append(np.zeros(len(data)))

        # 加权平均
        weights = np.array(self.weights)
        weights = weights / weights.sum()
        avg_pos = sum(w * p for w, p in zip(weights, positions))

        # 生成信号
        position = pd.Series(
            (avg_pos >= self.threshold).astype(float),
            index=data.index,
        )
        signal = position.diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        result = pd.DataFrame({
            "date": data["date"].values if "date" in data.columns else data.index,
            "close": data["close"].values,
            "position": position.values,
            "signal": signal.values,
        })

        return result.reset_index(drop=True)


class AdaptiveEnsemble(EnsembleStrategy):
    """
    自适应权重集成 v2

    根据各策略最近60天滚动夏普比率动态调整权重。
    只有最近表现优于随机（sharpe > 0）的策略才参与集成。

    用法:
        strat = AdaptiveEnsemble()
        signals = strat.generate(price_data)
    """

    def __init__(
        self,
        strategies: Optional[List] = None,
        lookback: int = 60,
        min_sharpe: float = 0.0,
        threshold: float = 0.5,
    ):
        if strategies is None:
            self.strategies = [
                TripleFactorStrategy(),
                MomentumFactorStrategy(),
            ]
        else:
            self.strategies = strategies

        self.lookback = lookback
        self.min_sharpe = min_sharpe  # 最小夏普门槛，低于此值权重归零
        self.threshold = threshold
        # 缓存最近计算的性能权重
        self._cached_weights = None
        self._cache_date = None

    def generate(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        n = len(self.strategies)
        weights = np.zeros(n)
        valid_count = 0

        for i, strat in enumerate(self.strategies):
            sig = strat.generate(data, **kwargs)
            if "position" not in sig.columns or sig.empty:
                continue

            eq_df, ret, sharpe = _backtest_fast(data, sig)
            # 夏普低于门槛则权重归零
            if sharpe >= self.min_sharpe:
                weights[i] = max(sharpe, 0)
                valid_count += 1

        # 如果所有策略都不行，回退到等权
        if valid_count == 0:
            weights = np.ones(n)
        else:
            weights = weights / weights.sum()

        self._cached_weights = weights

        # 加权平均position
        positions = []
        for strat in self.strategies:
            sig = strat.generate(data, **kwargs)
            if "position" in sig.columns:
                positions.append(sig["position"].values)
            else:
                positions.append(np.zeros(len(data)))

        avg_pos = sum(w * p for w, p in zip(weights, positions))

        position = pd.Series(
            (avg_pos >= self.threshold).astype(float),
            index=data.index,
        )
        signal = position.diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        # weights列：每行相同权重，展平成(n_rows, n_strats)
        weights_arr = np.tile(weights, (len(data), 1))

        result = pd.DataFrame({
            "date": data["date"].values if "date" in data.columns else data.index,
            "close": data["close"].values,
            "position": position.values,
            "signal": signal.values,
            "weights": list(weights_arr),
        })

        return result.reset_index(drop=True)


class VotingEnsemble:
    """
    投票式集成

    各策略给出多空信号（1=做多, -1=做空, 0=空仓），
    统计投票结果决定最终仓位。

    用法:
        strat = VotingEnsemble()
        signals = strat.generate(price_data)
    """

    def __init__(
        self,
        strategies: Optional[List] = None,
        vote_threshold: float = 0.5,
    ):
        if strategies is None:
            self.strategies = [
                TripleFactorStrategy(),
                MomentumFactorStrategy(),
            ]
        else:
            self.strategies = strategies

        # vote_threshold: 多少比例的策略做多才算通过
        self.vote_threshold = vote_threshold

    def generate(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        n_strats = len(self.strategies)
        votes = []

        for strat in self.strategies:
            sig = strat.generate(data, **kwargs)
            if "position" in sig.columns:
                # position > 0.5 → 1, else → 0
                vote = (sig["position"].values > 0.5).astype(int)
            else:
                vote = np.zeros(len(data))
            votes.append(vote)

        votes = np.array(votes)  # shape: (n_strats, n_days)
        avg_vote = votes.mean(axis=0)  # shape: (n_days,)

        # 超过threshold比例的策略做多 → 全仓
        position = pd.Series(
            (avg_vote >= self.vote_threshold).astype(float),
            index=data.index,
        )
        signal = position.diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        result = pd.DataFrame({
            "date": data["date"].values if "date" in data.columns else data.index,
            "close": data["close"].values,
            "position": position.values,
            "signal": signal.values,
        })

        return result.reset_index(drop=True)


class RegimeSwitchingEnsemble:
    """
    状态切换集成

    根据市场状态（趋势/震荡）自动切换策略组合：
    - 趋势市（MA多头排列）：以动量策略为主
    - 震荡市（MA空头排列）：以均值回归/低波动策略为主

    用法:
        strat = RegimeSwitchingEnsemble()
        signals = strat.generate(price_data)
    """

    def __init__(
        self,
        lookback_ma: int = 60,
        mom_weight_trend: float = 0.7,
        mom_weight_range: float = 0.3,
        mean_rev_weight_trend: float = 0.3,
        mean_rev_weight_range: float = 0.7,
    ):
        self.lookback_ma = lookback_ma
        # 趋势态权重
        self.mom_weight_trend = mom_weight_trend
        self.mean_rev_weight_trend = mean_rev_weight_trend
        # 震荡态权重
        self.mom_weight_range = mom_weight_range
        self.mean_rev_weight_range = mean_rev_weight_range

    def _detect_regime(self, data: pd.DataFrame) -> pd.Series:
        """检测市场状态：trend=1, range=0"""
        close = data["close"]
        ma_short = close.rolling(20).mean()
        ma_long = close.rolling(self.lookback_ma).mean()
        # 趋势态：短期MA > 长期MA，且价格 > 长期MA
        trend = ((ma_short > ma_long) & (close > ma_long)).astype(int)
        return trend

    def generate(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        from strategies.mean_reversion import RSI_Strat

        # 检测市场状态
        regime = self._detect_regime(data)

        # 各类策略
        mom_strat = MomentumFactorStrategy()
        triple_strat = TripleFactorStrategy()
        rsi_strat = RSI_Strat(14)

        mom_sig = mom_strat.generate(data)
        triple_sig = triple_strat.generate(data)
        rsi_sig = rsi_strat.generate(data)

        positions = []
        for i in range(len(data)):
            is_trend = regime.iloc[i] == 1

            if is_trend:
                # 趋势态：动量为主
                mom_w = self.mom_weight_trend
                triple_w = self.mean_rev_weight_trend  # triple当防御用
            else:
                # 震荡态：均值回归为主
                mom_w = self.mom_weight_range
                triple_w = self.mean_rev_weight_range

            total = mom_w + triple_w
            pos = (
                mom_w / total * mom_sig["position"].iloc[i]
                + triple_w / total * triple_sig["position"].iloc[i]
            )
            positions.append(pos)

        position = pd.Series(positions, index=data.index)
        position = (position > 0.5).astype(float)
        signal = position.diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        result = pd.DataFrame({
            "date": data["date"].values if "date" in data.columns else data.index,
            "close": data["close"].values,
            "regime": regime.values,
            "position": position.values,
            "signal": signal.values,
        })

        return result.reset_index(drop=True)
