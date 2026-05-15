from execution.paper import PaperTrader, OrderSide
from execution.risk_controls import PortfolioRiskPolicy


def test_paper_trader_respects_risk_policy_on_buy():
    trader = PaperTrader(initial_cash=100_000)
    trader.risk_policy = PortfolioRiskPolicy(max_single_position_ratio=0.2, max_positions=5)
    ok = trader.buy("2024-01-02", "510300", price=4.0, amount=30_000)
    assert ok is False


def test_trade_recommendation_contains_explanation():
    trader = PaperTrader(initial_cash=100_000)
    rec = trader.build_trade_recommendation(
        symbol="510300",
        side=OrderSide.BUY,
        model_score=0.72,
        industry_score=0.66,
        risk_note="max drawdown control active",
    )
    assert "510300" in rec["summary"]
    assert "model_score" in rec
