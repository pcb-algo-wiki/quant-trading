"""
趋势跟踪策略
"""

import pandas as pd
import numpy as np
from .base import Strategy


class MA_Cross(Strategy):
    """
    双均线交叉策略
    - 金叉买入，死叉卖出
    """

    def __init__(self, fast: int = 5, slow: int = 20):
        super().__init__(f"MA_Cross({fast},{slow})")
        self.fast = fast
        self.slow = slow

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["ma_fast"] = df["close"].rolling(self.fast).mean()
        df["ma_slow"] = df["close"].rolling(self.slow).mean()

        # 多头仓位
        df["position"] = np.where(df["ma_fast"] > df["ma_slow"], 1, 0)

        # 信号：仓位变化时产生交易
        df["signal"] = df["position"].diff().fillna(0).astype(int)
        # signal: 1=买入, -1=卖出, 0=持有

        return df[["open", "high", "low", "close", "volume",
                    "ma_fast", "ma_slow", "position", "signal"]]


class MACD_Strat(Strategy):
    """
    MACD策略
    - DIF上穿DEA买入，下穿卖出
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(f"MACD({fast},{slow},{signal})")
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        ema_fast = df["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.slow, adjust=False).mean()
        df["dif"] = ema_fast - ema_slow
        df["dea"] = df["dif"].ewm(span=self.signal, adjust=False).mean()
        df["macd"] = (df["dif"] - df["dea"]) * 2

        # DIF在DEA上方且DIF>0，多头
        df["position"] = np.where((df["dif"] > df["dea"]) & (df["dif"] > 0), 1, 0)
        df["signal"] = df["position"].diff().fillna(0).astype(int)

        return df[["open", "high", "low", "close", "volume",
                    "dif", "dea", "macd", "position", "signal"]]


class Breakout_20(Strategy):
    """
    20日突破策略
    - 价格突破20日高点买入，跌破20日低点卖出
    """

    def __init__(self, lookback: int = 20):
        super().__init__(f"Breakout({lookback})")
        self.lookback = lookback

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["highest"] = df["high"].rolling(self.lookback).max()
        df["lowest"] = df["low"].rolling(self.lookback).min()

        # 突破最高点买入，跌穿最低点卖出
        df["position"] = np.where(df["close"] > df["highest"].shift(1), 1, 0)
        df["position"] = np.where(df["close"] < df["lowest"].shift(1), 0, df["position"])

        df["signal"] = df["position"].diff().fillna(0).astype(int)

        return df[["open", "high", "low", "close", "volume",
                    "highest", "lowest", "position", "signal"]]
