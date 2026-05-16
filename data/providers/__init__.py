"""数据提供者层

统一接口：DataProvider ABC
路由入口：DataRouter

用法：
    from data.providers import DataRouter
    router = DataRouter()
    df = router.fetch_ohlcv("510300", "20230101", "20241231")
"""
from data.providers.router import DataRouter

__all__ = ["DataRouter"]
