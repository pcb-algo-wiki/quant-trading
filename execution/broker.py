from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class BrokerAdapter(ABC):
    @abstractmethod
    def place_order(self, symbol: str, side: str, price: float, qty: float) -> dict:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_order(self, broker_order_id: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_account(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> dict:
        raise NotImplementedError


class MockBrokerAdapter(BrokerAdapter):
    def __init__(self, initial_cash: float = 100_000):
        self.cash = float(initial_cash)
        self.orders: dict[str, dict] = {}
        self.positions: dict[str, float] = {}
        self._seq = 0

    def place_order(self, symbol: str, side: str, price: float, qty: float) -> dict:
        self._seq += 1
        broker_order_id = f"mock-{self._seq:06d}"
        order = {
            "broker_order_id": broker_order_id,
            "status": "accepted",
            "symbol": symbol,
            "side": side,
            "price": float(price),
            "qty": float(qty),
        }
        self.orders[broker_order_id] = order
        return order

    def cancel_order(self, broker_order_id: str) -> bool:
        order = self.orders.get(broker_order_id)
        if not order:
            return False
        if order["status"] in ("filled", "cancelled", "rejected"):
            return False
        order["status"] = "cancelled"
        return True

    def get_order(self, broker_order_id: str) -> Optional[dict]:
        return self.orders.get(broker_order_id)

    def get_account(self) -> dict:
        return {"cash": self.cash, "equity": self.cash}

    def get_positions(self) -> dict:
        return dict(self.positions)


class ReplayBrokerAdapter(BrokerAdapter):
    """
    回放模式：place_order 时按预设序列返回结果，用于仿真/联调一致性验证。
    """

    def __init__(self, replay: list[dict], initial_cash: float = 100_000):
        self.replay = list(replay)
        self.cash = float(initial_cash)
        self.orders: dict[str, dict] = {}
        self.positions: dict[str, float] = {}
        self._idx = 0

    def place_order(self, symbol: str, side: str, price: float, qty: float) -> dict:
        if self._idx < len(self.replay):
            template = dict(self.replay[self._idx])
            self._idx += 1
        else:
            template = {"broker_order_id": f"replay-{self._idx}", "status": "accepted"}
            self._idx += 1
        order = {
            "broker_order_id": template.get("broker_order_id", f"replay-{self._idx}"),
            "status": template.get("status", "accepted"),
            "symbol": symbol,
            "side": side,
            "price": float(price),
            "qty": float(qty),
            "fill_price": template.get("fill_price"),
            "fill_qty": template.get("fill_qty"),
            "reason": template.get("reason", ""),
        }
        self.orders[order["broker_order_id"]] = order
        return order

    def cancel_order(self, broker_order_id: str) -> bool:
        order = self.orders.get(broker_order_id)
        if not order:
            return False
        if order["status"] in ("filled", "cancelled", "rejected"):
            return False
        order["status"] = "cancelled"
        return True

    def get_order(self, broker_order_id: str) -> Optional[dict]:
        return self.orders.get(broker_order_id)

    def get_account(self) -> dict:
        return {"cash": self.cash, "equity": self.cash}

    def get_positions(self) -> dict:
        return dict(self.positions)
