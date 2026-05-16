"""Tushare Pro 数据提供者（付费，可选）

需要 tushare token：
  - 设置环境变量 TUSHARE_TOKEN 或
  - 在 config.yaml providers.tushare.token 配置

未配置 token 或未安装 tushare 包时 is_available() 返回 False。
"""
from __future__ import annotations

import os

import pandas as pd

from data.providers.base import DataProvider


class TushareProvider(DataProvider):
    """Tushare Pro A 股日线数据提供者。"""

    def __init__(self, token: str = "") -> None:
        self.token = token or os.getenv("TUSHARE_TOKEN", "")

    def get_name(self) -> str:
        return "tushare"

    def is_available(self) -> bool:
        if not self.token:
            return False
        try:
            import tushare  # noqa: F401
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
        if not self.is_available():
            return pd.DataFrame()

        try:
            import tushare as ts
            ts.set_token(self.token)
            pro = ts.pro_api()

            # Tushare 代码格式：000001.SZ / 600519.SH
            ts_code = self._to_ts_code(symbol)
            start_d = start.replace("-", "")
            end_d = end.replace("-", "")

            df = pro.daily(ts_code=ts_code, start_date=start_d, end_date=end_d)
            if df is None or df.empty:
                return pd.DataFrame()

            df = df.rename(columns={
                "trade_date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "vol": "volume",
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df[["date", "open", "high", "low", "close", "volume"]].copy()

        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        """将 6 位代码转为 Tushare ts_code。"""
        if "." in symbol:
            return symbol
        if symbol.startswith(("6", "9")):
            return f"{symbol}.SH"
        if symbol.startswith(("51", "58")):
            return f"{symbol}.SH"
        return f"{symbol}.SZ"
