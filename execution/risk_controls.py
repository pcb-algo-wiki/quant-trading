from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PortfolioRiskPolicy:
    max_single_position_ratio: float = 0.2
    max_positions: int = 10

    def check_buy_allowed(
        self,
        current_equity: float,
        current_positions: int,
        existing_position_value: float,
        buy_notional: float,
    ) -> tuple[bool, str]:
        if current_positions >= self.max_positions and existing_position_value <= 0:
            return False, "max_positions_limit"

        next_value = existing_position_value + buy_notional
        if current_equity > 0 and (next_value / current_equity) > self.max_single_position_ratio:
            return False, "single_position_limit"
        return True, "ok"
