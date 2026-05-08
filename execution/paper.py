"""
模拟交易模块
- 跟踪持仓、资金、盈亏
- 生成交易信号
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, asdict


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
        return (self.current_price - self.avg_cost) / self.avg_cost


@dataclass
class Trade:
    date: str
    symbol: str
    action: str  # BUY/SELL
    price: float
    shares: float
    pnl: float = 0  # 平仓盈亏（仅SELL时计算）


class PaperTrader:
    """
    模拟交易账户
    """

    def __init__(self, initial_cash: float = 100_000, config_path: str = ""):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}  # symbol -> Position
        self.trades: List[Trade] = []
        self.equity_curve: List[dict] = []
        self.config_path = config_path

    def buy(self, date: str, symbol: str, price: float, shares: float = 0, amount: float = 0):
        """
        买入

        Args:
            date: 交易日期
            symbol: 股票代码
            price: 价格
            shares: 股数（优先使用）
            amount: 金额（shares=0时使用）
        """
        if shares == 0 and amount > 0:
            shares = amount / price

        cost = shares * price * 1.0003  # 手续费
        if cost > self.cash:
            print(f"[警告] 资金不足: 需要{cost:.2f}, 账户{self.cash:.2f}")
            return False

        if symbol in self.positions:
            pos = self.positions[symbol]
            total_shares = pos.shares + shares
            pos.avg_cost = (pos.shares * pos.avg_cost + shares * price) / total_shares
            pos.shares = total_shares
            pos.current_price = price
        else:
            self.positions[symbol] = Position(
                symbol=symbol, shares=shares, avg_cost=price, current_price=price
            )

        self.cash -= cost
        self.trades.append(Trade(date, symbol, "BUY", price, shares))
        print(f"[BUY] {date} {symbol} {shares:.0f}股 @{price:.2f}")
        return True

    def sell(self, date: str, symbol: str, price: float, shares: float = 0):
        """卖出"""
        if symbol not in self.positions:
            print(f"[警告] 没有持仓: {symbol}")
            return False

        pos = self.positions[symbol]
        if shares == 0 or shares >= pos.shares:
            shares = pos.shares

        proceeds = shares * price * 0.9997  # 扣除手续费
        pnl = (price - pos.avg_cost) * shares

        self.cash += proceeds
        self.trades.append(Trade(date, symbol, "SELL", price, shares, pnl))

        pos.shares -= shares
        if pos.shares <= 0:
            del self.positions[symbol]
        else:
            pos.current_price = price

        print(f"[SELL] {date} {symbol} {shares:.0f}股 @{price:.2f} PnL={pnl:.2f}")
        return True

    def update_prices(self, prices: dict[str, float]):
        """更新持仓价格"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = price

    def get_equity(self) -> float:
        """当前总权益"""
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
        """获取账户统计"""
        equity = self.get_equity()
        total_return = (equity - self.initial_cash) / self.initial_cash

        winning_trades = [t for t in self.trades if t.action == "SELL" and t.pnl > 0]
        losing_trades = [t for t in self.trades if t.action == "SELL" and t.pnl < 0]

        return {
            "initial_cash": self.initial_cash,
            "current_equity": equity,
            "cash": self.cash,
            "total_return": total_return,
            "total_return_pct": f"{total_return*100:.2f}%",
            "num_positions": len(self.positions),
            "num_trades": len(self.trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": len(winning_trades) / max(len(winning_trades) + len(losing_trades), 1),
        }

    def print_status(self):
        """打印账户状态"""
        stats = self.get_stats()
        print(f"\n{'='*45}")
        print(f"  模拟账户状态")
        print(f"{'='*45}")
        print(f"  {'初始资金':>12}: {stats['initial_cash']:>10.2f}")
        print(f"  {'当前权益':>12}: {stats['current_equity']:>10.2f}")
        print(f"  {'现金':>12}: {stats['cash']:>10.2f}")
        print(f"  {'总收益率':>12}: {stats['total_return_pct']:>10}")
        print(f"  {'持仓数':>12}: {stats['num_positions']:>10}")
        print(f"  {'交易次数':>12}: {stats['num_trades']:>10}")
        print(f"  {'胜率':>12}: {stats['win_rate']*100:>10.2f}%")
        print(f"{'='*45}")

        if self.positions:
            print("\n持仓:")
            for pos in self.positions.values():
                print(
                    f"  {pos.symbol}: {pos.shares:.0f}股 @ "
                    f"成本={pos.avg_cost:.2f} 当前={pos.current_price:.2f} "
                    f"盈亏={pos.unrealized_pnl:.2f}({pos.return_pct*100:.1f}%)"
                )

    def save(self, path: str = "results/paper_trades.json"):
        """保存交易记录"""
        Path(path).parent.mkdir(exist_ok=True)
        data = {
            "stats": self.get_stats(),
            "trades": [asdict(t) for t in self.trades],
            "equity_curve": self.equity_curve,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"\n[已保存] {path}")


if __name__ == "__main__":
    # 简单测试
    trader = PaperTrader(initial_cash=100_000)
    trader.buy("2024-01-01", "000001", 10.0, amount=10000)
    trader.update_prices({"000001": 11.0})
    trader.sell("2024-01-10", "000001", 11.0)
    trader.snapshot("2024-01-10")
    trader.print_status()
