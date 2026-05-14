from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PortfolioRiskPolicy:
    max_single_position_ratio: float = 0.2
    max_positions: int = 10
    max_industry_ratio: float = 0.35
    max_drawdown_limit: float = 0.2

    def check_buy_allowed(
        self,
        current_equity: float,
        current_positions: int,
        existing_position_value: float,
        buy_notional: float,
        current_industry_value: float = 0.0,
    ) -> tuple[bool, str]:
        if current_positions >= self.max_positions and existing_position_value <= 0:
            return False, "max_positions_limit"

        next_value = existing_position_value + buy_notional
        if current_equity > 0 and (next_value / current_equity) > self.max_single_position_ratio:
            return False, "single_position_limit"
        industry_next = current_industry_value + buy_notional
        if current_equity > 0 and (industry_next / current_equity) > self.max_industry_ratio:
            return False, "industry_limit"
        return True, "ok"

    def check_drawdown_guard(self, peak_equity: float, current_equity: float) -> bool:
        if peak_equity <= 0:
            return True
        drawdown = (peak_equity - current_equity) / peak_equity
        return drawdown <= self.max_drawdown_limit
