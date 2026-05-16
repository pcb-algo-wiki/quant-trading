"""AkShare 数据提供者

AkShare 开源免费，支持 A 股、ETF、港股等多市场。
若 akshare 未安装则 is_available() 返回 False。
"""
from __future__ import annotations

import pandas as pd

from data.providers.base import DataProvider


class AkShareProvider(DataProvider):
    """AkShare A 股 / ETF 数据提供者。"""

    def get_name(self) -> str:
        return "akshare"

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
            return True
        except ImportError:
            return False

    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        freq: str = "daily",
    ) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError:
            return pd.DataFrame()

        start_d = start.replace("-", "")
        end_d = end.replace("-", "")

        try:
            # ETF 基金历史行情
            if symbol.startswith(("51", "15", "58", "16")):
                df = ak.fund_etf_hist_em(
                    symbol=symbol,
                    period="daily",
                    start_date=start_d,
                    end_date=end_d,
                    adjust="qfq",
                )
                col_map = {"日期": "date", "开盘": "open", "最高": "high",
                           "最低": "low", "收盘": "close", "成交量": "volume"}
            else:
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_d,
                    end_date=end_d,
                    adjust="qfq",
                )
                col_map = {"日期": "date", "开盘": "open", "最高": "high",
                           "最低": "low", "收盘": "close", "成交量": "volume"}

            if df is None or df.empty:
                return pd.DataFrame()

            df = df.rename(columns=col_map)
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")

            return df[["date", "open", "high", "low", "close", "volume"]].copy()

        except Exception:
            return pd.DataFrame()
