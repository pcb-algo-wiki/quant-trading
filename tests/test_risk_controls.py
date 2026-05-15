from execution.risk_controls import PortfolioRiskPolicy


def test_portfolio_risk_policy_blocks_overweight_trade():
    policy = PortfolioRiskPolicy(max_single_position_ratio=0.2, max_positions=5)
    allowed, reason = policy.check_buy_allowed(
        current_equity=100_000,
        current_positions=2,
        existing_position_value=5_000,
        buy_notional=30_000,
    )
    assert allowed is False
    assert "single_position_limit" in reason
