"""规则化 Regime 检测与权重调度

替代 RL 中央代理：基于波动率 / 最大回撤 / 情感均值三档投票，
决定长线 Alpha 策略与事件驱动策略的组合权重。

档位定义：
    bull   — 低波动 + 低回撤 + 正情绪
    neutral — 中等水平
    bear   — 高波动 or 大回撤 or 负情绪
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_WEIGHT_TABLE: dict[str, dict[str, float]] = {
    "bull":    {"long_alpha": 0.7, "event_driven": 0.3},
    "neutral": {"long_alpha": 0.5, "event_driven": 0.5},
    "bear":    {"long_alpha": 0.3, "event_driven": 0.7},
}


class RegimeDetector:
    """基于规则的市场状态检测。

    Args:
        vol_bull: 年化波动率 < vol_bull → bull 投票
        vol_bear: 年化波动率 > vol_bear → bear 投票
        dd_bull:  最大回撤 > dd_bull（绝对值小）→ bull 投票，例如 -0.05
        dd_bear:  最大回撤 < dd_bear（绝对值大）→ bear 投票，例如 -0.15
        sent_bull: 情感均值 > sent_bull → bull 投票
        sent_bear: 情感均值 < sent_bear → bear 投票
    """

    def __init__(
        self,
        vol_bull: float = 0.15,
        vol_bear: float = 0.25,
        dd_bull: float = -0.05,
        dd_bear: float = -0.15,
        sent_bull: float = 0.1,
        sent_bear: float = -0.1,
    ) -> None:
        self.vol_bull = vol_bull
        self.vol_bear = vol_bear
        self.dd_bull = dd_bull
        self.dd_bear = dd_bear
        self.sent_bull = sent_bull
        self.sent_bear = sent_bear

    # ── 检测 ──────────────────────────────────────────────────────────────────

    def detect(
        self,
        price: pd.Series,
        avg_sentiment: float = 0.0,
        vol_window: int = 20,
        dd_window: int = 60,
    ) -> str:
        """检测市场 Regime。

        Args:
            price: 收盘价 Series（日频）
            avg_sentiment: 近期情感均值，[-1, 1]
            vol_window: 波动率计算窗口（天）
            dd_window: 最大回撤计算窗口（天）

        Returns:
            'bull' | 'neutral' | 'bear'
        """
        votes = 0  # +1 = bull, -1 = bear

        # 波动率投票
        vol = self._compute_vol(price, vol_window)
        if vol < self.vol_bull:
            votes += 1
        elif vol > self.vol_bear:
            votes -= 1

        # 最大回撤投票
        dd = self._compute_max_drawdown(price, dd_window)
        if dd > self.dd_bull:  # 回撤小（接近 0）→ bull
            votes += 1
        elif dd < self.dd_bear:  # 回撤大 → bear
            votes -= 1

        # 情感投票
        sent = float(avg_sentiment)
        if sent > self.sent_bull:
            votes += 1
        elif sent < self.sent_bear:
            votes -= 1

        if votes > 0:
            return "bull"
        if votes < 0:
            return "bear"
        return "neutral"

    # ── 权重 ─────────────────────────────────────────────────────────────────

    def get_weights(self, regime: str) -> dict[str, float]:
        """根据 Regime 返回策略权重。

        Returns:
            {'long_alpha': float, 'event_driven': float}，权重和 = 1。
        """
        return dict(_WEIGHT_TABLE.get(regime, _WEIGHT_TABLE["neutral"]))

    # ── 辅助计算 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_vol(price: pd.Series, window: int) -> float:
        """年化滚动波动率（最近 window 天，不足则全量）。"""
        if len(price) < 2:
            return 0.0
        n = min(window, len(price))
        returns = price.iloc[-n:].pct_change().dropna()
        if returns.empty:
            return 0.0
        return float(returns.std() * np.sqrt(252))

    @staticmethod
    def _compute_max_drawdown(price: pd.Series, window: int) -> float:
        """最近 window 天内最大回撤（负数）。"""
        if len(price) < 2:
            return 0.0
        n = min(window, len(price))
        sub = price.iloc[-n:]
        peak = sub.expanding().max()
        dd = ((sub - peak) / peak.replace(0, np.nan)).min()
        return float(dd) if not np.isnan(dd) else 0.0
