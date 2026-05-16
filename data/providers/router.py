"""数据路由层

根据标的类型选择最优数据提供者：
  A 股 / ETF（纯数字代码） → SinaProvider → AkShareProvider → TushareProvider
  美股（字母 ticker）        → PolygonProvider → YFinanceProvider

配置路由（config.yaml providers 段）可覆盖默认顺序：

  providers:
    a_share_order: [sina, akshare, tushare]
    us_order: [polygon, yfinance]
    tushare:
      token: ""
    polygon:
      api_key: ""
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from data.providers.base import DataProvider
from data.providers.sina import SinaProvider
from data.providers.akshare_provider import AkShareProvider
from data.providers.tushare_provider import TushareProvider
from data.providers.polygon_provider import PolygonProvider, YFinanceProvider


_PROVIDER_REGISTRY: dict[str, type[DataProvider]] = {
    "sina": SinaProvider,
    "akshare": AkShareProvider,
    "tushare": TushareProvider,
    "polygon": PolygonProvider,
    "yfinance": YFinanceProvider,
}


class DataRouter:
    """标的路由器：按优先级尝试数据提供者，首次成功返回。

    Args:
        a_share_order: A 股提供者优先级列表（名称字符串）
        us_order: 美股提供者优先级列表
        tushare_token: Tushare token（可选）
        polygon_api_key: Polygon API key（可选）
        a_share_chain: 直接传入提供者实例（测试用，优先于 a_share_order）
        us_chain: 直接传入提供者实例（测试用，优先于 us_order）
    """

    def __init__(
        self,
        a_share_order: Optional[list[str]] = None,
        us_order: Optional[list[str]] = None,
        tushare_token: str = "",
        polygon_api_key: str = "",
        a_share_chain: Optional[list[DataProvider]] = None,
        us_chain: Optional[list[DataProvider]] = None,
    ) -> None:
        self._a_share_order = a_share_order or ["sina", "akshare", "tushare"]
        self._us_order = us_order or ["polygon", "yfinance"]
        self._tushare_token = tushare_token
        self._polygon_api_key = polygon_api_key
        # 预建实例（优先级高于名称列表）
        self._a_share_chain: Optional[list[DataProvider]] = a_share_chain
        self._us_chain: Optional[list[DataProvider]] = us_chain

    def _build_provider(self, name: str) -> Optional[DataProvider]:
        cls = _PROVIDER_REGISTRY.get(name)
        if cls is None:
            return None
        if name == "tushare":
            return TushareProvider(token=self._tushare_token)
        if name == "polygon":
            return PolygonProvider(api_key=self._polygon_api_key)
        return cls()

    @staticmethod
    def _is_us_symbol(symbol: str) -> bool:
        """纯字母或字母数字混合（非 6 位纯数字）判断为美股。"""
        return bool(symbol) and not symbol.isdigit()

    def fetch_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        freq: str = "daily",
    ) -> pd.DataFrame:
        """路由并获取 OHLCV 数据。

        依次尝试 available 的提供者，返回第一个非空结果。
        全部失败时抛出 RuntimeError。
        """
        is_us = self._is_us_symbol(symbol)

        # 优先使用直接注入的实例（测试场景）
        if is_us and self._us_chain is not None:
            provider_instances: list[DataProvider] = self._us_chain
        elif not is_us and self._a_share_chain is not None:
            provider_instances = self._a_share_chain
        else:
            provider_instances = []

        if provider_instances:
            last_error: Optional[Exception] = None
            for provider in provider_instances:
                if not provider.is_available():
                    continue
                try:
                    df = provider.fetch_ohlcv(symbol, start, end, freq)
                    if df is not None and not df.empty:
                        return df
                except Exception as e:
                    last_error = e
            raise RuntimeError(
                f"no provider succeeded for {symbol} ({start}~{end}). last_error={last_error}"
            )

        # 按名称列表构建并尝试
        provider_names = self._us_order if is_us else self._a_share_order
        last_error = None
        for name in provider_names:
            provider = self._build_provider(name)
            if provider is None or not provider.is_available():
                continue
            try:
                df = provider.fetch_ohlcv(symbol, start, end, freq)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                last_error = e

        raise RuntimeError(
            f"所有数据源均无法获取 {symbol} ({start}~{end})。"
            f"最后错误: {last_error}"
        )

    def list_providers(self, symbol: str = "") -> list[dict]:
        """列出候选提供者及可用状态（用于诊断）。"""
        names = (
            self._us_order
            if (symbol and self._is_us_symbol(symbol))
            else self._a_share_order
        )
        result = []
        for name in names:
            p = self._build_provider(name)
            result.append({
                "name": name,
                "available": p.is_available() if p else False,
            })
        return result


def build_router_from_cfg() -> DataRouter:
    """从 utils.config.cfg 构建 DataRouter（带异常兜底）。"""
    try:
        from utils.config import cfg
        providers_cfg = cfg.get("providers", {}) or {}
        return DataRouter(
            a_share_order=providers_cfg.get("a_share_order"),
            us_order=providers_cfg.get("us_order"),
            tushare_token=providers_cfg.get("tushare", {}).get("token", ""),
            polygon_api_key=providers_cfg.get("polygon", {}).get("api_key", ""),
        )
    except Exception:
        return DataRouter()
