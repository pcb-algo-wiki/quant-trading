"""新浪财经数据提供者

封装 data/fetcher.py 中已有的新浪 K 线接口。
支持 A 股 ETF、股票、指数的日线数据，无需 API Key。
"""
from __future__ import annotations

import pandas as pd

from data.providers.base import DataProvider


class SinaProvider(DataProvider):
    """新浪财经 A 股 / ETF 数据（封装 fetcher.py）。"""

    def get_name(self) -> str:
        return "sina"

    def is_available(self) -> bool:
        return True

    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        freq: str = "daily",
    ) -> pd.DataFrame:
        from data.fetcher import fetch_etf, fetch_stock

        # ETF：首位数字 1/5/1 开头
        is_etf = symbol.isdigit() and (
            symbol.startswith("51") or symbol.startswith("15")
            or symbol.startswith("58") or symbol.startswith("16")
        )

        try:
            if is_etf:
                df = fetch_etf(symbol, start, end)
            else:
                df = fetch_stock(symbol, start, end)
        except Exception:
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        # 统一输出格式
        df = df.copy()
        if "date" not in df.columns and df.index.name == "date":
            df = df.reset_index()
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "open", "high", "low", "close", "volume"]].copy()
