from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LiveGuard:
    require_manual_confirmation: bool = True
    max_consecutive_losses: int = 3
    max_slippage_bp: float = 30.0

    def can_place_live_order(
        self,
        manual_confirmed: bool,
        consecutive_losses: int,
        slippage_bp: float,
    ) -> tuple[bool, str]:
        if self.require_manual_confirmation and not manual_confirmed:
            return False, "manual_confirmation_required"
        if consecutive_losses > self.max_consecutive_losses:
            return False, "consecutive_loss_limit"
        if slippage_bp > self.max_slippage_bp:
            return False, "slippage_limit"
        return True, "ok"
