"""
execution/paper.py — 模拟交易增强版
====================================
- 订单状态机：pending → filled / rejected / cancelled
- 完整交易记录
- 盈亏统计
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

from execution.risk_controls import PortfolioRiskPolicy

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"      # 挂单中
    FILLED = "filled"        # 已成交
    PARTIAL = "partial"      # 部分成交
    CANCELLED = "cancelled"  # 已撤销
    REJECTED = "rejected"    # 已拒绝


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    """订单"""
    order_id: str
    date: str
    symbol: str
    side: OrderSide
    price: float
    target_shares: float       # 目标股数
    filled_shares: float = 0   # 已成交股数
    avg_fill_price: float = 0  # 成交均价
    status: OrderStatus = OrderStatus.PENDING
    reason: str = ""           # 拒绝/撤销原因
    created_at: str = ""       # 创建时间

    @property
    def unfilled_shares(self) -> float:
        return self.target_shares - self.filled_shares

    @property
    def is_complete(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


@dataclass
class Position:
    symbol: str
    shares: float
    avg_cost: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_cost) * self.shares

    @property
    def return_pct(self) -> float:
        return (self.current_price - self.avg_cost) / self.avg_cost if self.avg_cost > 0 else 0


@dataclass
class Trade:
    """成交记录"""
    trade_id: str
    order_id: str
    date: str
    symbol: str
    side: OrderSide
    price: float
    shares: float
    pnl: float = 0  # 平仓盈亏（仅SELL时）


class PaperTrader:
    """
    模拟交易账户（增强版：订单状态机）

    订单流程:
      submit_order() → 创建pending订单
      check_orders() → 更新订单状态
      execute_filled() → 执行成交，更新持仓
    """

    def __init__(
        self,
        initial_cash: float = 100_000,
        commission: float = 0.0003,
        slippage_pct: float = 0.0,
        fill_ratio: float = 1.0,
        latency_ms: int = 0,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission = commission
        self.slippage_pct = slippage_pct
        self.fill_ratio = max(0.0, min(1.0, fill_ratio))
        self.latency_ms = latency_ms
        self.risk_policy = PortfolioRiskPolicy()
        self.positions: Dict[str, Position] = {}
        self.orders: List[Order] = []
        self.trades: List[Trade] = []
        self.equity_curve: List[dict] = []
        self._order_counter = 0
        self._trade_counter = 0

    # ---- 订单管理 ----

    def submit_order(
        self,
        date: str,
        symbol: str,
        side: OrderSide,
        price: float,
        shares: float,
        order_id: str = None,
    ) -> Order:
        """提交订单（挂单）"""
        if order_id is None:
            self._order_counter += 1
            order_id = f"ORD-{self._order_counter:04d}"

        order = Order(
            order_id=order_id,
            date=date,
            symbol=symbol,
            side=side,
            price=price,
            target_shares=shares,
            created_at=datetime.now().strftime("%H:%M:%S"),
        )
        self.orders.append(order)
        logger.info(f"[Order] {order.status.value.upper()} {side.value} {symbol} {shares}@{price}")
        return order

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        for order in self.orders:
            if order.order_id == order_id and order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                order.reason = "user_cancel"
                logger.info(f"[Order Cancelled] {order_id}")
                return True
        return False

    def check_and_fill(self, current_prices: Dict[str, float]) -> List[Order]:
        """
        检查所有pending订单，更新状态
        简化逻辑：市价 >= 挂单价则成交

        Returns:
            本次新成交的订单列表
        """
        filled_orders = []
        today = date.today().strftime("%Y-%m-%d")

        for order in self.orders:
            if order.status != OrderStatus.PENDING:
                continue

            current_price = current_prices.get(order.symbol, order.price)

            # 简单撮合逻辑：买单价>=市价则成交，卖单价<=市价则成交
            if order.side == OrderSide.BUY and current_price <= order.price * 1.01:
                # 买入：允许1%滑点内成交
                self._fill_order(order, current_price, order.target_shares)
                filled_orders.append(order)
            elif order.side == OrderSide.SELL and current_price >= order.price * 0.99:
                # 卖出：允许1%滑点内成交
                self._fill_order(order, current_price, order.target_shares)
                filled_orders.append(order)

        return filled_orders

    def _fill_order(self, order: Order, fill_price: float, fill_shares: float):
        """执行成交"""
        # 仿真参数：成交比例 + 滑点
        executable_shares = fill_shares * self.fill_ratio
        if order.side == OrderSide.BUY:
            actual_price = fill_price * (1 + self.slippage_pct)
        else:
            actual_price = fill_price * (1 - self.slippage_pct)

        order.avg_fill_price = actual_price
        order.filled_shares = executable_shares
        order.status = OrderStatus.FILLED if executable_shares >= order.target_shares else OrderStatus.PARTIAL

        self._trade_counter += 1
        trade = Trade(
            trade_id=f"TRD-{self._trade_counter:04d}",
            order_id=order.order_id,
            date=order.date,
            symbol=order.symbol,
            side=order.side,
            price=actual_price,
            shares=executable_shares,
        )

        if order.side == OrderSide.BUY:
            self._execute_buy(order, actual_price, executable_shares, trade)
        else:
            self._execute_sell(order, actual_price, executable_shares, trade)

        self.trades.append(trade)
        logger.info(f"[Fill] {order.side.value} {order.symbol} {executable_shares}@{actual_price:.3f}")

    def _execute_buy(self, order: Order, price: float, shares: float, trade: Trade):
        """执行买入"""
        cost = shares * price * (1 + self.commission)
        if cost > self.cash:
            order.status = OrderStatus.REJECTED
            order.reason = f"insufficient_cash: need={cost:.2f} have={self.cash:.2f}"
            logger.warning(f"[Reject] {order.order_id} {order.reason}")
            return

        self.cash -= cost

        if order.symbol in self.positions:
            pos = self.positions[order.symbol]
            total = pos.shares + shares
            pos.avg_cost = (pos.shares * pos.avg_cost + shares * price) / total
            pos.shares = total
            pos.current_price = price
        else:
            self.positions[order.symbol] = Position(
                symbol=order.symbol, shares=shares,
                avg_cost=price, current_price=price
            )

    def _execute_sell(self, order: Order, price: float, shares: float, trade: Trade):
        """执行卖出"""
        if order.symbol not in self.positions:
            order.status = OrderStatus.REJECTED
            order.reason = f"no_position: {order.symbol}"
            logger.warning(f"[Reject] {order.order_id} {order.reason}")
            return

        pos = self.positions[order.symbol]
        if shares > pos.shares:
            shares = pos.shares  # 最多卖完

        proceeds = shares * price * (1 - self.commission)
        pnl = (price - pos.avg_cost) * shares
        trade.pnl = pnl

        self.cash += proceeds
        pos.shares -= shares
        if pos.shares <= 0:
            del self.positions[order.symbol]
        else:
            pos.current_price = price

    # ---- 便捷方法 ----

    def buy(self, date: str, symbol: str, price: float, shares: float = 0, amount: float = 0) -> bool:
        """快捷买入（市价单，不经过订单状态机）"""
        if shares == 0 and amount > 0:
            shares = amount / price
        buy_notional = shares * price
        existing_position_value = self.positions[symbol].market_value if symbol in self.positions else 0.0
        allowed, reason = self.risk_policy.check_buy_allowed(
            current_equity=self.get_equity(),
            current_positions=len(self.positions),
            existing_position_value=existing_position_value,
            buy_notional=buy_notional,
        )
        if not allowed:
            logger.warning(f"[Risk] buy rejected {symbol}: {reason}")
            return False

        self._order_counter += 1
        order = Order(
            order_id=f"ORD-{self._order_counter:04d}",
            date=date, symbol=symbol,
            side=OrderSide.BUY, price=price,
            target_shares=shares,
            created_at=datetime.now().strftime("%H:%M:%S"),
        )
        # 直接以挂单价成交
        self._fill_order(order, price, shares)
        self.orders.append(order)
        return order.status == OrderStatus.FILLED

    def build_trade_recommendation(
        self,
        symbol: str,
        side: OrderSide,
        model_score: float,
        industry_score: float,
        risk_note: str,
    ) -> dict:
        summary = (
            f"{side.value} {symbol} | model={model_score:.3f} "
            f"industry={industry_score:.3f} | risk={risk_note}"
        )
        return {
            "symbol": symbol,
            "side": side.value,
            "model_score": model_score,
            "industry_score": industry_score,
            "risk_note": risk_note,
            "summary": summary,
        }

    def validate_execution_consistency(self) -> dict:
        """
        检查订单-成交-持仓-账户一致性。
        """
        issues = []
        calc_equity = self.cash + sum(p.market_value for p in self.positions.values())
        if calc_equity < 0:
            issues.append("negative_equity")
        for order in self.orders:
            if order.status == OrderStatus.FILLED and order.filled_shares <= 0:
                issues.append(f"filled_without_shares:{order.order_id}")
            if order.status == OrderStatus.PARTIAL and order.filled_shares >= order.target_shares:
                issues.append(f"partial_but_full:{order.order_id}")
        return {"ok": len(issues) == 0, "issues": issues, "equity": calc_equity}

    def sell(self, date: str, symbol: str, price: float, shares: float = 0) -> bool:
        """快捷卖出"""
        if shares == 0 and symbol in self.positions:
            shares = self.positions[symbol].shares

        self._order_counter += 1
        order = Order(
            order_id=f"ORD-{self._order_counter:04d}",
            date=date, symbol=symbol,
            side=OrderSide.SELL, price=price,
            target_shares=shares,
            created_at=datetime.now().strftime("%H:%M:%S"),
        )
        self._fill_order(order, price, shares)
        self.orders.append(order)
        return order.status == OrderStatus.FILLED

    def update_prices(self, prices: Dict[str, float]):
        """批量更新持仓价格"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = price

    def get_equity(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    def snapshot(self, date: str):
        """记录每日权益"""
        equity = self.get_equity()
        self.equity_curve.append({
            "date": date,
            "cash": self.cash,
            "equity": equity,
            "positions_value": equity - self.cash,
            "return": (equity - self.initial_cash) / self.initial_cash,
        })

    def get_stats(self) -> dict:
        equity = self.get_equity()
        total_return = (equity - self.initial_cash) / self.initial_cash

        sell_trades = [t for t in self.trades if t.side == OrderSide.SELL]
        winning = [t for t in sell_trades if t.pnl > 0]

        pending_orders = [o for o in self.orders if o.status == OrderStatus.PENDING]

        return {
            "initial_cash": self.initial_cash,
            "current_equity": equity,
            "cash": self.cash,
            "total_return": total_return,
            "total_return_pct": f"{total_return*100:.2f}%",
            "num_positions": len(self.positions),
            "num_trades": len(self.trades),
            "num_orders": len(self.orders),
            "pending_orders": len(pending_orders),
            "winning_trades": len(winning),
            "losing_trades": len(sell_trades) - len(winning),
            "win_rate": len(winning) / max(len(sell_trades), 1),
        }

    def get_positions_summary(self) -> List[dict]:
        """持仓汇总"""
        return [
            {
                "symbol": p.symbol,
                "shares": round(p.shares, 0),
                "avg_cost": round(p.avg_cost, 3),
                "current_price": round(p.current_price, 3),
                "market_value": round(p.market_value, 2),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "return_pct": f"{p.return_pct*100:.2f}%",
            }
            for p in self.positions.values()
        ]

    def print_status(self):
        stats = self.get_stats()
        print(f"\n{'='*50}")
        print(f"  模拟账户状态  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
        print(f"{'='*50}")
        print(f"  {'初始资金':>12}: {stats['initial_cash']:>12.2f}")
        print(f"  {'当前权益':>12}: {stats['current_equity']:>12.2f}")
        print(f"  {'现金':>12}: {stats['cash']:>12.2f}")
        print(f"  {'总收益率':>12}: {stats['total_return_pct']:>12}")
        print(f"  {'持仓数':>12}: {stats['num_positions']:>12}")
        print(f"  {'成交单数':>12}: {stats['num_trades']:>12}")
        print(f"  {'挂单数':>12}: {stats['pending_orders']:>12}")
        print(f"  {'胜率':>12}: {stats['win_rate']*100:>11.2f}%")
        print(f"{'='*50}")

        if self.positions:
            print("\n持仓:")
            for p in self.positions.values():
                emoji = "🟢" if p.unrealized_pnl >= 0 else "🔴"
                print(f"  {emoji} {p.symbol}: {p.shares:.0f}股 "
                      f"成本={p.avg_cost:.3f} 现价={p.current_price:.3f} "
                      f"盈亏={p.unrealized_pnl:.2f}({p.return_pct*100:+.1f}%)")

        if self.orders:
            pending = [o for o in self.orders if o.status == OrderStatus.PENDING]
            if pending:
                print(f"\n挂单({len(pending)}笔):")
                for o in pending[-5:]:
                    print(f"  ⏳ {o.order_id} {o.side.value} {o.symbol} {o.target_shares:.0f}@{o.price:.3f}")

    def save(self, path: str = "results/paper_trades.json"):
        Path(path).parent.mkdir(exist_ok=True)
        data = {
            "stats": self.get_stats(),
            "positions": self.get_positions_summary(),
            "orders": [asdict(o) for o in self.orders],
            "trades": [asdict(t) for t in self.trades],
            "equity_curve": self.equity_curve,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n[已保存] {path}")


# ============ 兼容旧接口 ============

def PaperTraderLegacy(**kwargs):
    """保留旧版PaperTrader接口供旧代码兼容"""
    return PaperTrader(**kwargs)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    trader = PaperTrader(initial_cash=100_000)
    trader.buy("2024-01-01", "510300", 3.85, amount=38500)
    trader.update_prices({"510300": 4.00})
    trader.sell("2024-01-15", "510300", 4.00)
    trader.snapshot("2024-01-15")
    trader.print_status()
    trader.save("results/paper_test.json")
