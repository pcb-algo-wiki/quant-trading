"""
策略基类 - 所有策略的父类
"""

from abc import ABC, abstractmethod
import pandas as pd
from typing import Optional


class Strategy(ABC):
    """策略抽象基类"""

    def __init__(self, name: str = ""):
        self.name = name or self.__class__.__name__

    @abstractmethod
    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成信号

        Args:
            data: OHLCV数据，必须包含 open, high, low, close, volume 列

        Returns:
            DataFrame with added columns:
            - signal: 1(买入), -1(卖出), 0(持有)
            - position: 1(多头), 0(空仓)
        """
        pass

    def __repr__(self):
        return f"{self.name}()"
