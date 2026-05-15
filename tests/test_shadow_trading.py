import pandas as pd

from scripts.shadow_trading import run_shadow_session


def test_run_shadow_session_reports_slippage_delta():
    recommendations = [
        {"symbol": "510300", "side": "BUY", "target_price": 4.00, "qty": 1000},
        {"symbol": "510500", "side": "SELL", "target_price": 6.00, "qty": 500},
    ]
    market_fills = pd.DataFrame(
        {
            "symbol": ["510300", "510500"],
            "fill_price": [4.03, 5.95],
        }
    )
    result = run_shadow_session(recommendations, market_fills)
    assert result["n_orders"] == 2
    assert "avg_slippage_bp" in result
