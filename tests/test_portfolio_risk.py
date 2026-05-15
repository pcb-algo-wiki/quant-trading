from execution.risk_controls import PortfolioRiskPolicy


def test_industry_limit_blocks_buy():
    policy = PortfolioRiskPolicy(max_single_position_ratio=0.4, max_positions=10, max_industry_ratio=0.3)
    allowed, reason = policy.check_buy_allowed(
        current_equity=100_000,
        current_positions=2,
        existing_position_value=5_000,
        buy_notional=15_000,
        current_industry_value=20_000,
    )
    assert allowed is False
    assert reason == "industry_limit"


def test_drawdown_guard_triggers_circuit_break():
    policy = PortfolioRiskPolicy(max_drawdown_limit=0.15)
    assert policy.check_drawdown_guard(peak_equity=100_000, current_equity=80_000) is False
