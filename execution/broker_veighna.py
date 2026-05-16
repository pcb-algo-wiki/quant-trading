"""VeighNa 模拟适配器骨架（dry-run）

Phase 5 仅实现骨架接口，保持与 BrokerAdapter 一致。
默认 dry_run=True，不连接真实柜台。
Phase 7 升级时将 dry_run=False 并接入 vnpy gateway。

用法:
    from execution.broker_veighna import VeighNaBrokerAdapter
    broker = VeighNaBrokerAdapter()          # dry_run=True
    order = broker.place_order("510300", "BUY", 4.50, 1000)
    # -> {'broker_order_id': 'vn-000001', 'status': 'accepted', ...}
"""
from __future__ import annotations

import logging
from typing import Optional

from execution.broker import BrokerAdapter

logger = logging.getLogger(__name__)


class VeighNaBrokerAdapter(BrokerAdapter):
    """VeighNa 风格的 BrokerAdapter，Phase 5 始终 dry_run。

    Args:
        dry_run: 必须为 True（Phase 7 前禁止改为 False）。
        initial_cash: 模拟账户初始资金。
    """

    def __init__(
        self,
        dry_run: bool = True,
        initial_cash: float = 100_000.0,
    ) -> None:
        if not dry_run:
            raise ValueError(
                "VeighNaBrokerAdapter: dry_run=False 已被 R4 风控规则禁止。"
                "Phase 7 接入真实柜台前请保持 dry_run=True。"
            )
        self.dry_run = dry_run
        self._cash = float(initial_cash)
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, float] = {}
        self._seq = 0

    # ── BrokerAdapter 接口 ────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        qty: float,
    ) -> dict:
        """模拟 vnpy 成交回报（dry_run 始终立即成交）。"""
        self._seq += 1
        order_id = f"vn-{self._seq:06d}"

        notional = float(price) * float(qty)
        status = "accepted"

        # 简单风控：资金不足则拒绝
        if side.upper() == "BUY" and notional > self._cash:
            status = "rejected"
            logger.warning("[VeighNa dry-run] 资金不足，拒绝买单 %s qty=%s", symbol, qty)
        else:
            if side.upper() == "BUY":
                self._cash -= notional
                self._positions[symbol] = self._positions.get(symbol, 0.0) + float(qty)
            elif side.upper() == "SELL":
                held = self._positions.get(symbol, 0.0)
                sold = min(float(qty), held)
                self._positions[symbol] = held - sold
                self._cash += float(price) * sold

        order = {
            "broker_order_id": order_id,
            "status": status,
            "symbol": symbol,
            "side": side.upper(),
            "price": float(price),
            "qty": float(qty),
            "fill_price": float(price) if status == "accepted" else None,
            "fill_qty": float(qty) if status == "accepted" else 0.0,
            "gateway": "veighna_dry_run",
        }
        self._orders[order_id] = order
        logger.info("[VeighNa dry-run] %s %s %s qty=%s price=%s → %s",
                    side, symbol, order_id, qty, price, status)
        return order

    def cancel_order(self, broker_order_id: str) -> bool:
        order = self._orders.get(broker_order_id)
        if not order:
            return False
        if order["status"] in ("filled", "cancelled", "rejected"):
            return False
        order["status"] = "cancelled"
        return True

    def get_order(self, broker_order_id: str) -> Optional[dict]:
        return self._orders.get(broker_order_id)

    def get_account(self) -> dict:
        equity = self._cash + sum(
            self._positions.get(sym, 0.0) * 0.0  # 无实时价格，以成本估算
            for sym in self._positions
        )
        return {
            "cash": self._cash,
            "equity": self._cash,  # dry-run: equity ≈ cash（无 mark-to-market）
            "gateway": "veighna_dry_run",
        }

    def get_positions(self) -> dict:
        return {sym: qty for sym, qty in self._positions.items() if qty > 0}
