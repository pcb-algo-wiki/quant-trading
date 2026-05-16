"""DataProvider 抽象基类

所有数据提供者必须实现此接口，保证输出格式统一：
  date(str YYYY-MM-DD), open, high, low, close, volume
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataProvider(ABC):
    """数据提供者抽象基类。"""

    @abstractmethod
    def get_name(self) -> str:
        """返回提供者唯一名称（如 'sina', 'akshare', 'tushare', 'polygon'）。"""

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        freq: str = "daily",
    ) -> pd.DataFrame:
        """获取 OHLCV 日线（或其他频率）数据。

        Args:
            symbol: 标的代码（A股 6 位数字，美股 ticker）
            start: 开始日期 "YYYYMMDD" 或 "YYYY-MM-DD"
            end:   结束日期 "YYYYMMDD" 或 "YYYY-MM-DD"
            freq:  频率（"daily" | "weekly" | "monthly"），默认日线

        Returns:
            DataFrame，必须含列：date, open, high, low, close, volume。
            date 列为 datetime 或可 pd.to_datetime 转换的字符串。
            若无数据则返回空 DataFrame。
        """

    def is_available(self) -> bool:
        """返回提供者当前是否可用（API key 已配置 / 依赖包已安装）。"""
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.get_name()} available={self.is_available()}>"
