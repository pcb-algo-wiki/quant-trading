from execution.live_guard import LiveGuard


def test_live_guard_blocks_when_manual_confirmation_missing():
    guard = LiveGuard(require_manual_confirmation=True, max_consecutive_losses=3)
    allowed, reason = guard.can_place_live_order(
        manual_confirmed=False,
        consecutive_losses=0,
        slippage_bp=5,
    )
    assert allowed is False
    assert reason == "manual_confirmation_required"


def test_live_guard_blocks_when_consecutive_losses_exceeded():
    guard = LiveGuard(require_manual_confirmation=False, max_consecutive_losses=2)
    allowed, reason = guard.can_place_live_order(
        manual_confirmed=True,
        consecutive_losses=3,
        slippage_bp=5,
    )
    assert allowed is False
    assert reason == "consecutive_loss_limit"
