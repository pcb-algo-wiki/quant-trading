from execution.broker import MockBrokerAdapter, ReplayBrokerAdapter


def test_mock_broker_supports_order_lifecycle():
    broker = MockBrokerAdapter(initial_cash=100000)
    order = broker.place_order(symbol="510300", side="BUY", price=4.0, qty=1000)
    assert order["status"] == "accepted"
    fetched = broker.get_order(order["broker_order_id"])
    assert fetched["symbol"] == "510300"
    assert broker.cancel_order(order["broker_order_id"]) is True
    assert broker.get_order(order["broker_order_id"])["status"] == "cancelled"


def test_replay_broker_returns_predefined_fills():
    replay = [
        {"broker_order_id": "r-1", "status": "filled", "fill_price": 4.01, "fill_qty": 1000},
        {"broker_order_id": "r-2", "status": "rejected", "reason": "liquidity"},
    ]
    broker = ReplayBrokerAdapter(replay=replay, initial_cash=100000)
    o1 = broker.place_order(symbol="510300", side="BUY", price=4.0, qty=1000)
    o2 = broker.place_order(symbol="510300", side="BUY", price=4.0, qty=1000)
    assert o1["status"] == "filled"
    assert o2["status"] == "rejected"
