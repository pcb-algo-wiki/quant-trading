from __future__ import annotations

from abc import ABC, abstractmethod


class BrokerAdapter(ABC):
    @abstractmethod
    def place_order(self, symbol: str, side: str, price: float, qty: float) -> dict:
        raise NotImplementedError


class MockBrokerAdapter(BrokerAdapter):
    def place_order(self, symbol: str, side: str, price: float, qty: float) -> dict:
        return {
            "broker_order_id": f"mock-{symbol}-{side}",
            "status": "accepted",
            "symbol": symbol,
            "side": side,
            "price": price,
            "qty": qty,
        }
