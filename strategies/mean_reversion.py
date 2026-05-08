"""
均值回归策略
"""

import pandas as pd
import numpy as np
from .base import Strategy


class RSI_Strat(Strategy):
    """
    RSI策略
    - RSI<30超卖买入，RSI>70超买卖出
    """

    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        super().__init__(f"RSI({period})")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.period).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        df["position"] = 0
        df.loc[df["rsi"] < self.oversold, "position"] = 1   # 超卖买入
        df.loc[df["rsi"] > self.overbought, "position"] = 0  # 超买卖出

        df["signal"] = df["position"].diff().fillna(0).astype(int)

        return df[["open", "high", "low", "close", "volume",
                    "rsi", "position", "signal"]]


class BollingerBand(Strategy):
    """
    布林带策略
    - 价格下穿布林带下轨买入，上穿上轨卖出
    """

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        super().__init__(f"BB({period},{std_dev})")
        self.period = period
        self.std_dev = std_dev

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        df["mid"] = df["close"].rolling(self.period).mean()
        df["std"] = df["close"].rolling(self.period).std()
        df["upper"] = df["mid"] + self.std_dev * df["std"]
        df["lower"] = df["mid"] - self.std_dev * df["std"]

        df["position"] = 0
        df.loc[df["close"] < df["lower"], "position"] = 1  # 买入
        df.loc[df["close"] > df["upper"], "position"] = 0  # 卖出

        df["signal"] = df["position"].diff().fillna(0).astype(int)

        return df[["open", "high", "low", "close", "volume",
                    "mid", "upper", "lower", "position", "signal"]]


class KD_Strat(Strategy):
    """
    KDJ随机指标策略
    - K<20超卖买入，K>80超买卖出
    """

    def __init__(self, n: int = 9, m1: int = 3, m2: int = 3):
        super().__init__(f"KD({n},{m1},{m2})")
        self.n = n
        self.m1 = m1
        self.m2 = m2

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        low_n = df["low"].rolling(self.n).min()
        high_n = df["high"].rolling(self.n).max()

        df["rsv"] = (df["close"] - low_n) / (high_n - low_n) * 100
        df["r"] = df["rsv"].ewm(alpha=1/self.m1, adjust=False).mean()
        df["k"] = df["r"].ewm(alpha=1/self.m2, adjust=False).mean()
        df["j"] = 3 * df["k"] - 2 * df["r"]

        df["position"] = 0
        df.loc[df["k"] < 20, "position"] = 1
        df.loc[df["k"] > 80, "position"] = 0

        df["signal"] = df["position"].diff().fillna(0).astype(int)

        return df[["open", "high", "low", "close", "volume",
                    "k", "d", "j", "position", "signal"]]
