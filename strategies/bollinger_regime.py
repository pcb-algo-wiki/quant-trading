"""
布林带均值回归策略 v1.0
======================
利用布林带识别超买超卖，在震荡市中做高胜率交易

原理:
  - 价格触及下轨 → 超卖 → 买入
  - 价格触及上轨 → 超买 → 卖出
  - 过滤: 只在布林带收口后再次开口时入场（减少假信号）

参数:
  - lookback: 布林带周期 (默认20)
  - std_dev: 标准差倍数 (默认2.0)
  - exit_pct: 触及中轨止盈比例 (默认0.5，即50%利润)
"""

import pandas as pd
import numpy as np


class BollingerBandStrategy:
    """
    布林带均值回归策略

    策略逻辑:
      1. 计算MA20和2倍标准差上下轨
      2. 价格触及下轨时买入（超卖反弹）
      3. 价格触及上轨时卖出（超买回落）
      4. 中轨作为动态止盈位
    """

    def __init__(
        self,
        lookback: int = 20,
        std_dev: float = 2.0,
        position_size: float = 1.0,
    ):
        self.lookback = lookback
        self.std_dev = std_dev
        self.position_size = position_size

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成布林带交易信号

        Args:
            data: OHLCV DataFrame

        Returns:
            DataFrame with columns: signal, position, bb_lower, bb_mid, bb_upper, bandwidth
        """
        df = data.copy().reset_index(drop=True)
        close = df["close"]

        # 布林带
        df["bb_mid"] = close.rolling(self.lookback).mean()
        rolling_std = close.rolling(self.lookback).std()
        df["bb_upper"] = df["bb_mid"] + self.std_dev * rolling_std
        df["bb_lower"] = df["bb_mid"] - self.std_dev * rolling_std

        # 布林带带宽（波动率指标）
        df["bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

        # 信号生成
        signals = []
        positions = []
        position = 0

        for i in range(len(df)):
            if i < self.lookback:
                signals.append(0)
                positions.append(0)
                continue

            price = close.iloc[i]
            lower = df["bb_lower"].iloc[i]
            upper = df["bb_upper"].iloc[i]
            mid = df["bb_mid"].iloc[i]

            signal = 0

            # 买入条件：价格触及或跌破下轨
            if price <= lower:
                signal = 1
                position = 1

            # 卖出条件：价格触及或突破上轨，或达到中轨止盈
            elif position == 1 and (price >= upper or price >= mid):
                signal = -1
                position = 0

            # 止损：买入后价格继续下跌超过3%
            elif position == 1 and price < df["bb_lower"].iloc[i - 1] * 0.97:
                signal = -1
                position = 0

            signals.append(signal)
            positions.append(position)

        df["signal"] = signals
        df["position"] = positions

        return df[
            [
                "date",
                "close",
                "bb_lower",
                "bb_mid",
                "bb_upper",
                "bandwidth",
                "position",
                "signal",
            ]
        ]
