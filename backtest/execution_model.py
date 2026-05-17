"""Phase 15.2 — 成交模型

实现两个主流市场冲击模型：
- VWAP 滑点：随参与率线性放大
- 平方根流动性冲击：经典 Almgren 模型
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class VWAPSlippageModel:
    """VWAP 滑点（bp）。

    bp = base_bp + participation_coef * participation_rate（百分比形式）
    """

    base_bp: float = 2.0
    participation_coef: float = 10.0

    def estimate_bp(self, order_volume: float, avg_volume: float) -> float:
        if avg_volume <= 0:
            return self.base_bp
        participation = min(order_volume / avg_volume, 1.0)
        return self.base_bp + self.participation_coef * participation


@dataclass
class SquareRootImpactModel:
    """平方根市场冲击（bp）。

    impact_bp = coef * daily_volatility * sqrt(order_volume / avg_volume) * 10000
    """

    coef: float = 0.1
    daily_volatility: float = 0.02  # 例：2% 日波动率

    def estimate_bp(self, order_volume: float, avg_volume: float) -> float:
        if avg_volume <= 0 or order_volume <= 0:
            return 0.0
        ratio = order_volume / avg_volume
        return self.coef * self.daily_volatility * math.sqrt(ratio) * 10000


def combined_fill_price(
    *,
    side: str,
    mid_price: float,
    order_volume: float,
    avg_volume: float,
    slippage_model: VWAPSlippageModel,
    impact_model: SquareRootImpactModel | None = None,
) -> float:
    """组合滑点 + 冲击 → 成交价。

    买入价高于 mid，卖出价低于 mid。
    """
    total_bp = slippage_model.estimate_bp(order_volume, avg_volume)
    if impact_model is not None:
        total_bp += impact_model.estimate_bp(order_volume, avg_volume)
    adj = mid_price * total_bp / 10000.0
    if side == "buy":
        return mid_price + adj
    return mid_price - adj
