"""Phase 15.2 — 成交模型测试"""
from __future__ import annotations

import pytest

from backtest.execution_model import (
    VWAPSlippageModel,
    SquareRootImpactModel,
    combined_fill_price,
)


def test_vwap_slippage_increases_with_participation():
    """参与率越高，滑点越大。"""
    model = VWAPSlippageModel(base_bp=2.0, participation_coef=10.0)
    low_part = model.estimate_bp(order_volume=100, avg_volume=10000)  # 1%
    high_part = model.estimate_bp(order_volume=5000, avg_volume=10000)  # 50%
    assert high_part > low_part
    assert low_part >= 2.0  # 至少基础滑点


def test_vwap_slippage_zero_volume_returns_base():
    model = VWAPSlippageModel(base_bp=3.0, participation_coef=5.0)
    bp = model.estimate_bp(order_volume=100, avg_volume=0)
    assert bp == 3.0


def test_square_root_impact_scales_with_sqrt_volume():
    """成交量 4 倍，冲击约 2 倍（sqrt）。"""
    model = SquareRootImpactModel(coef=1.0, daily_volatility=0.02)
    impact_low = model.estimate_bp(order_volume=100, avg_volume=10000)
    impact_high = model.estimate_bp(order_volume=400, avg_volume=10000)
    ratio = impact_high / impact_low
    assert 1.9 < ratio < 2.1


def test_combined_fill_price_buy_increases_price():
    fill = combined_fill_price(
        side="buy",
        mid_price=100.0,
        order_volume=100,
        avg_volume=10000,
        slippage_model=VWAPSlippageModel(base_bp=5.0, participation_coef=0.0),
    )
    assert fill > 100.0
    # 5bp = 0.05%
    assert abs(fill - 100.05) < 0.001


def test_combined_fill_price_sell_decreases_price():
    fill = combined_fill_price(
        side="sell",
        mid_price=100.0,
        order_volume=100,
        avg_volume=10000,
        slippage_model=VWAPSlippageModel(base_bp=5.0, participation_coef=0.0),
    )
    assert fill < 100.0
