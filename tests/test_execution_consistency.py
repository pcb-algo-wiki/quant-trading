from execution.paper import PaperTrader


def test_paper_trader_execution_consistency_check():
    trader = PaperTrader(initial_cash=100000)
    trader.buy("2024-01-02", "510300", price=4.0, amount=10000)
    trader.update_prices({"510300": 4.1})
    report = trader.validate_execution_consistency()
    assert report["ok"] is True
    assert report["issues"] == []
