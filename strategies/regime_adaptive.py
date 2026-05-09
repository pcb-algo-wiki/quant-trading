"""
市场环境自适应策略 v1.0
========================
根据市场环境自动切换仓位和ETF选择的智能策略

原理:
  - 牛市(价格上涨+趋势向上): 持仓不动，超配创业板
  - 熊市(价格下跌+趋势向下): MA信号止损，空仓或配置债券
  - 震荡(无明显趋势): 轮动策略超额收益

判断方法:
  - 趋势: MA20 > MA60 → 牛市, MA20 < MA60 → 熊市
  - 动量: 20日收益率 > 0 → 正动量
  - 波动率: Bollinger带宽 > 历史均值 → 高波动

参数:
  - bull_position: 牛市仓位 (默认1.0)
  - bear_position: 熊市仓位 (默认0.0)
  - bull_etf: 牛市ETF (默认创业板159915)
  - bear_etf: 熊市ETF (默认空仓)
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple


class RegimeAdaptiveStrategy:
    """
    市场环境自适应策略

    策略逻辑:
      1. 计算MA20/MA60判断趋势方向
      2. 计算20日动量判断价格方向
      3. 结合两者判断牛熊/震荡
      4. 根据环境分配仓位和ETF

    环境状态:
      - BULL:    MA20 > MA60 AND 动量 > 0    → 持仓100%
      - BEAR:    MA20 < MA60 AND 动量 < 0    → 空仓0%
      - MIXED:   其他情况                    → 轮动策略
    """

    def __init__(
        self,
        bull_etf: str = "159915",
        bear_etf: str = None,
        ma_fast: int = 20,
        ma_slow: int = 60,
        momentum_window: int = 20,
        use_rotation_fallback: bool = True,
    ):
        self.bull_etf = bull_etf
        self.bear_etf = bear_etf
        self.ma_fast = ma_fast
        self.ma_slow = ma_slow
        self.momentum_window = momentum_window
        self.use_rotation_fallback = use_rotation_fallback

    def detect_regime(
        self, df: pd.DataFrame
    ) -> Tuple[str, str, float]:
        """
        检测市场环境

        Returns:
            (regime, trend_direction, momentum_pct)
            regime: 'BULL' | 'BEAR' | 'MIXED'
            trend_direction: 'up' | 'down' | 'flat'
            momentum_pct: 20日动量百分比
        """
        close = df["close"]

        # 均线
        ma_fast = close.rolling(self.ma_fast).mean()
        ma_slow = close.rolling(self.ma_slow).mean()

        # 动量
        momentum = close.pct_change(self.momentum_window)

        latest = len(df) - 1
        ma_f = ma_fast.iloc[latest] if not np.isnan(ma_fast.iloc[latest]) else close.iloc[latest]
        ma_s = ma_slow.iloc[latest] if not np.isnan(ma_slow.iloc[latest]) else close.iloc[latest]
        mom = momentum.iloc[latest] if not np.isnan(momentum.iloc[latest]) else 0.0

        # 趋势
        if ma_f > ma_s * 1.01:
            trend = "up"
        elif ma_f < ma_s * 0.99:
            trend = "down"
        else:
            trend = "flat"

        # 动量方向
        if mom > 0.01:
            mom_dir = "positive"
        elif mom < -0.01:
            mom_dir = "negative"
        else:
            mom_dir = "neutral"

        # 综合判断
        if trend == "up" and mom_dir == "positive":
            regime = "BULL"
        elif trend == "down" and mom_dir == "negative":
            regime = "BEAR"
        else:
            regime = "MIXED"

        return regime, trend, mom

    def generate(
        self, data: pd.DataFrame, rotation_signals: Optional[dict] = None
    ) -> pd.DataFrame:
        """
        生成自适应信号

        Args:
            data: 主ETF的OHLC数据
            rotation_signals: 可选，轮动策略的信号dict，用于MIXED状态

        Returns:
            DataFrame with regime, position, signal columns
        """
        df = data.copy().reset_index(drop=True)
        close = df["close"]

        # 均线
        df["ma_fast"] = close.rolling(self.ma_fast).mean()
        df["ma_slow"] = close.rolling(self.ma_slow).mean()

        # 动量
        df["momentum"] = close.pct_change(self.momentum_window)

        # 检测环境
        regimes = []
        trends = []
        for i in range(len(df)):
            if i < self.ma_slow:
                regimes.append("UNKNOWN")
                trends.append("flat")
                continue

            sub = df.iloc[: i + 1]
            reg, trend, mom = self.detect_regime(sub)
            regimes.append(reg)
            trends.append(trend)

        df["regime"] = regimes
        df["trend"] = trends

        # 生成持仓和信号
        positions = []
        signals = []

        for i in range(len(df)):
            reg = df["regime"].iloc[i]

            if reg == "BULL":
                positions.append(1)
                signals.append(1 if (i > 0 and df["regime"].iloc[i - 1] != "BULL") else 0)
            elif reg == "BEAR":
                positions.append(0)
                signals.append(-1 if (i > 0 and df["regime"].iloc[i - 1] not in ("BEAR", "UNKNOWN")) else 0)
            else:  # MIXED / UNKNOWN
                if self.use_rotation_fallback and rotation_signals is not None:
                    # 使用轮动信号
                    pos = rotation_signals.get("position", 0) if isinstance(rotation_signals, dict) else 0
                    positions.append(pos)
                    signals.append(0)  # 轮动信号自己带信号
                else:
                    positions.append(0)
                    signals.append(0)

        df["position"] = positions
        df["signal"] = signals

        return df[["date", "close", "ma_fast", "ma_slow", "momentum", "regime", "trend", "position", "signal"]]

    def get_regime_description(self, regime: str) -> str:
        descriptions = {
            "BULL": "牛市环境 — 趋势向上+正动量，建议满仓持有",
            "BEAR": "熊市环境 — 趋势向下+负动量，建议空仓等待",
            "MIXED": "震荡环境 — 趋势不明，建议使用轮动策略",
            "UNKNOWN": "数据不足，无法判断",
        }
        return descriptions.get(regime, "未知环境")
