"""
tests/conftest.py
=================
pytest fixtures — 共享测试数据
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import sys

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def sample_ohlcv():
    """正常的OHLCV数据"""
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    np.random.seed(42)
    
    close = 100 + np.cumsum(np.random.randn(100) * 2)
    high = close + np.abs(np.random.randn(100))
    low = close - np.abs(np.random.randn(100))
    open_price = low + np.random.rand(100) * (high - low)
    volume = np.random.randint(1_000_000, 10_000_000, 100)
    
    return pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def sample_signals():
    """正常信号"""
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    signal = [0] * 20 + [1] * 30 + [-1] * 10 + [0] * 40
    position = [0] * 20 + [1] * 30 + [0] * 50
    
    return pd.DataFrame({
        "date": dates,
        "signal": signal[:100],
        "position": position[:100],
    })


@pytest.fixture
def dirty_ohlcv():
    """有质量问题的OHLCV数据"""
    dates = pd.date_range("2024-01-01", periods=20, freq="B")
    
    # 正常数据
    close = [100, 101, 102, 103, 104] * 4
    high = [105, 106, 107, 108, 109] * 4
    low = [99, 98, 97, 96, 95] * 4
    open_price = [100, 101, 102, 103, 104] * 4
    volume = [1_000_000] * 20
    
    # 注入问题
    # Row 5: high < low (逻辑错误)
    high[5] = 100
    low[5] = 102
    
    # Row 10: volume = 0 (停牌)
    volume[10] = 0
    
    # Row 15: open > high (逻辑错误)
    open_price[15] = 110
    high[15] = 105
    
    # Row 18: close异常跳空 (人为注入outlier)
    close[18] = 200
    
    return pd.DataFrame({
        "date": dates,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def config_path(tmp_path):
    """临时配置文件"""
    import yaml
    config = {
        "data": {"cache_dir": "data/cache", "backtest": {"start": "20230101", "end": "20241231"}},
        "etfs": {
            "510300": {"name": "沪深300ETF", "enabled": True},
            "159915": {"name": "创业板ETF", "enabled": True},
        },
        "backtest": {
            "initial_capital": 100_000,
            "commission": 0.0003,
            "slippage": 0.0001,
        },
        "strategies": {
            "ma_cross": {"fast_period": 5, "slow_period": 20, "enabled": True},
        },
    }
    path = tmp_path / "test_config.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return str(path)
