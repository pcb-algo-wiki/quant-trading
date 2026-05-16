"""Polygon.io / yfinance 美股数据提供者

PolygonProvider：需要 POLYGON_API_KEY 环境变量（免费档有速率限制）
YFinanceProvider：无需 API key，作为 Polygon 的降级方案
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

from data.providers.base import DataProvider


class PolygonProvider(DataProvider):
    """Polygon.io 美股日线数据（REST v2）。"""

    BASE_URL = "https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key or os.getenv("POLYGON_API_KEY", "")

    def get_name(self) -> str:
        return "polygon"

    def is_available(self) -> bool:
        return bool(self.api_key)

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
            import requests

            from_date = self._normalize_date(start)
            to_date = self._normalize_date(end)

            url = self.BASE_URL.format(
                ticker=symbol.upper(),
                from_date=from_date,
                to_date=to_date,
            )
            resp = requests.get(url, params={"apiKey": self.api_key}, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                return pd.DataFrame()

            rows = []
            for r in results:
                rows.append({
                    "date": pd.to_datetime(r["t"], unit="ms"),
                    "open": r["o"],
                    "high": r["h"],
                    "low": r["l"],
                    "close": r["c"],
                    "volume": r["v"],
                })

            df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
            return df[["date", "open", "high", "low", "close", "volume"]]

        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """转为 YYYY-MM-DD 格式。"""
        d = date_str.replace("-", "")
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"


class YFinanceProvider(DataProvider):
    """yfinance 美股数据（免费，无 API Key，作为降级方案）。"""

    def get_name(self) -> str:
        return "yfinance"

    def is_available(self) -> bool:
        try:
            import yfinance  # noqa: F401
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
            import yfinance as yf

            start_d = self._normalize_date(start)
            end_d = self._normalize_date(end)

            ticker = yf.Ticker(symbol.upper())
            df = ticker.history(start=start_d, end=end_d)

            if df is None or df.empty:
                return pd.DataFrame()

            df = df.reset_index()
            df = df.rename(columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            return df[["date", "open", "high", "low", "close", "volume"]].copy()

        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        d = date_str.replace("-", "")
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
