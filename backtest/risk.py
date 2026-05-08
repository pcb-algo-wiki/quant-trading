"""
风控模块 - 仓位管理 + 止损机制
功能:
- 固定仓位 / 金字塔加仓 / 减仓策略
- 固定止损 + 跟踪止损
- 最大回撤熔断
- 动态仓位调整（根据波动率）
"""

import pandas as pd
import numpy as np
from typing import Optional, Literal
from dataclasses import dataclass, field


@dataclass
class PositionConfig:
    """仓位配置"""
    # 基础仓位
    base_ratio: float = 1.0        # 基础仓位比例（1.0=满仓）
    max_position: float = 1.0     # 最大仓位上限

    # 加仓策略
    pyramid: bool = False         # 是否允许金字塔加仓
    pyramid_steps: int = 3        # 加仓次数
    pyramid_ratio: float = 0.5    # 每次加仓仓位比例

    # 风控参数
    stop_loss: float = 0.07       # 固定止损（7%）
    take_profit: float = 0.20     # 止盈（20%）

    # 跟踪止损
    trailing_stop: bool = True
    trailing_pct: float = 0.05    # 跟踪止损（5%）

    # 波动率调整
    vol_adjust: bool = False      # 是否启用波动率调整
    vol_window: int = 20           # 波动率计算窗口
    vol_target: float = 0.15       # 目标年化波动率（15%）
    vol_max_ratio: float = 1.5    # 最大波动率调整倍数

    # 熔断机制
    daily_loss_limit: float = 0.03  # 单日最大亏损（3%）
    max_drawdown_limit: float = 0.20  # 最大回撤限制（20%）


@dataclass
class RiskState:
    """风控状态"""
    # 当前持仓
    position: float = 0.0          # 持股数量
    avg_price: float = 0.0         # 平均成本
    entry_date: Optional[str] = None

    # 止损状态
    stop_loss_price: float = 0.0   # 止损价
    take_profit_price: float = 0.0 # 止盈价
    highest_since_entry: float = 0.0  # 入场后最高价（用于跟踪止损）

    # 熔断状态
    current_date: Optional[str] = None  # 当前交易日期
    day_high_water: float = 0.0    # 当日最高权益
    day_low_water: float = float('inf')  # 当日最低权益
    equity_high: float = 0.0        # 历史最高权益（最大回撤用）

    # 波动率状态
    current_vol: float = 0.0       # 当前波动率


class RiskManager:
    """
    风控管理器

    用法:
        risk = RiskManager(config=PositionConfig(
            base_ratio=0.8,
            stop_loss=0.05,
            trailing_stop=True,
            trailing_pct=0.04,
        ))

        for each day:
            signal = strategy.generate(data)
            risk_signal = risk.check(
                current_date=date,
                current_price=price,
                current_equity=equity,
                signal=signal,  # 1=买入, -1=卖出, 0=持有
                position=current_position,
                avg_price=avg_cost,
            )
            # 执行 risk_signal（可能覆盖原始signal）
    """

    def __init__(self, config: Optional[PositionConfig] = None):
        self.config = config or PositionConfig()
        self.state = RiskState()

    def reset(self):
        """重置风控状态（新回测周期开始）"""
        self.state = RiskState()
    def check(
        self,
        current_date: str,
        current_price: float,
        current_equity: float,
        signal: int,
        position: float,
        avg_price: float,
        high_price: float = None,
    ) -> int:
        """
        检查风控信号

        Args:
            current_date: 当前日期
            current_price: 当前价格
            current_equity: 当前总权益
            signal: 原始策略信号（1=买入, -1=卖出, 0=持有）
            position: 当前持仓数量
            avg_price: 平均成本价
            high_price: 入场以来最高价

        Returns:
            风控后的信号（可能被风控覆盖）
        """
        s = self.state
        cfg = self.config

        # 新的一天开始，重置日水位线
        if s.current_date != current_date:
            s.current_date = current_date
            s.day_high_water = current_equity
            s.day_low_water = current_equity

        # 更新权益水位线
        if s.equity_high == 0:
            s.equity_high = current_equity
        else:
            s.equity_high = max(s.equity_high, current_equity)

        # 更新当日水位
        s.day_high_water = max(s.day_high_water, current_equity)
        s.day_low_water = min(s.day_low_water, current_equity)

        # 如果持仓中
        if position > 0:
            # ---- 止损检查 ----
            stop_signal = self._check_stop_loss(
                current_price, avg_price, high_price or current_price, position
            )
            if stop_signal != 0:
                self._log_signal(current_date, "止损", stop_signal)
                return stop_signal

            # ---- 熔断检查 ----
            if cfg.daily_loss_limit > 0:
                day_loss = (s.day_low_water - s.day_high_water) / s.day_high_water if s.day_high_water > 0 else 0
                if day_loss <= -cfg.daily_loss_limit:
                    self._log_signal(current_date, f"日熔断({day_loss*100:.1f}%)", -1)
                    return -1

            if cfg.max_drawdown_limit > 0:
                drawdown = (s.equity_high - current_equity) / s.equity_high if s.equity_high > 0 else 0
                if drawdown >= cfg.max_drawdown_limit:
                    self._log_signal(current_date, f"回撤熔断({drawdown*100:.1f}%)", -1)
                    return -1

            # ---- 跟踪止损检查 ----
            if cfg.trailing_stop and high_price:
                s.highest_since_entry = max(s.highest_since_entry, high_price)
                trailing_stop_price = s.highest_since_entry * (1 - cfg.trailing_pct)
                if current_price <= trailing_stop_price and s.stop_loss_price > 0:
                    self._log_signal(current_date, "跟踪止损", -1)
                    return -1

            # ---- 止盈检查 ----
            if cfg.take_profit > 0 and s.take_profit_price > 0:
                if current_price >= s.take_profit_price:
                    self._log_signal(current_date, "止盈", -1)
                    return -1

            # ---- 卖出信号 ----
            if signal == -1:
                return -1

            return 0  # 持有

        else:
            # 无持仓时：检查买入信号
            if signal == 1:
                # 波动率调整
                if cfg.vol_adjust:
                    vol_ratio = cfg.vol_target / max(s.current_vol, 0.001)
                    vol_ratio = min(vol_ratio, cfg.vol_max_ratio)
                    vol_ratio = max(vol_ratio, 0.3)
                    if vol_ratio < 0.8:
                        self._log_signal(current_date, f"波动率降仓({vol_ratio:.2f})", 0)
                        return 0

                return 1  # 允许买入

            return 0

    def on_fill(
        self,
        current_date: str,
        price: float,
        quantity: float,
        is_buy: bool,
        total_equity: float,
    ):
        """
        成交记录回调（更新风控状态）
        """
        s = self.state

        if is_buy:
            # 计算新的平均成本
            old_value = s.position * s.avg_price
            new_value = price * quantity
            total_qty = s.position + quantity

            if total_qty > 0:
                s.avg_price = (old_value + new_value) / total_qty
            s.position = total_qty

            if s.entry_date is None:
                s.entry_date = current_date

            # 设置止损价（仅首次建仓）
            if s.position == quantity:
                s.stop_loss_price = s.avg_price * (1 - self.config.stop_loss)
                s.take_profit_price = s.avg_price * (1 + self.config.take_profit)
                s.highest_since_entry = price
            else:
                # 金字塔加仓：更新止损为成本价
                s.stop_loss_price = min(s.stop_loss_price, s.avg_price * (1 - self.config.stop_loss))

        else:  # 卖出
            s.position = max(0, s.position - quantity)
            if s.position == 0:
                self._reset_position_state()

    def _check_stop_loss(
        self,
        current_price: float,
        avg_price: float,
        high_price: float,
        position: float,
    ) -> int:
        """检查是否触发止损"""
        cfg = self.config
        s = self.state

        if cfg.stop_loss <= 0:
            return 0

        # 固定止损
        if current_price <= s.stop_loss_price and s.stop_loss_price > 0:
            return -1

        # 金字塔加仓检查（暂时不做，保持简单）
        return 0

    def _reset_position_state(self):
        """重置持仓相关状态"""
        s = self.state
        s.position = 0
        s.avg_price = 0
        s.entry_date = None
        s.stop_loss_price = 0
        s.take_profit_price = 0
        s.highest_since_entry = 0

    def _log_signal(self, date: str, reason: str, signal: int):
        """打印风控信号（可扩展为日志）"""
        action = "买入" if signal == 1 else "卖出" if signal == -1 else "持有"
        print(f"  [风控] {date} {reason} → {action}")

    def update_volatility(self, returns: pd.Series):
        """更新波动率（每日收盘后调用）"""
        if len(returns) < self.config.vol_window:
            return
        rolling_ret = returns.tail(self.config.vol_window)
        annual_vol = rolling_ret.std() * np.sqrt(252)
        self.state.current_vol = annual_vol


# ============================================================
# 集成到回测引擎
# ============================================================

class BacktestEngineV2:
    """
    增强版回测引擎（带风控）

    与原版BacktestEngine的差异：
    - 支持仓位管理（可配置仓位比例）
    - 支持止损/止盈/跟踪止损
    - 支持波动率调整仓位
    - 支持日内熔断
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        commission: float = 0.0003,
        slippage: float = 0.0001,
        risk_config: Optional[PositionConfig] = None,
    ):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.risk = RiskManager(risk_config)
        self.risk_config = risk_config or PositionConfig()

    def run(self, data: pd.DataFrame, signals: pd.DataFrame) -> dict:
        """运行带风控的回测"""
        df = data.copy().reset_index(drop=True)
        sig = signals.copy().reset_index(drop=True)

        for col in sig.columns:
            if col not in df.columns:
                df[col] = sig[col]

        cash = self.initial_capital
        position = 0.0
        avg_price = 0.0
        records = []
        stop_loss_count = 0
        trades_count = 0

        risk = self.risk
        risk.reset()

        for i in range(len(df)):
            price = df.at[i, "close"]
            date = df.at[i, "date"]
            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
            signal = int(df.at[i, "signal"]) if "signal" in df.columns else 0
            equity = cash + position * price

            # 风控检查
            risk_signal = risk.check(
                current_date=date_str,
                current_price=price,
                current_equity=equity,
                signal=signal,
                position=position,
                avg_price=avg_price,
            )

            # 交易执行
            trade_executed = False
            is_buy = False
            traded_price = 0.0
            traded_qty = 0.0

            if risk_signal == 1 and cash > 0 and position == 0:
                # 买入（风控允许）
                buy_ratio = self.risk_config.base_ratio
                if self.risk_config.vol_adjust:
                    vol_ratio = self.risk_config.vol_target / max(risk.state.current_vol, 0.001)
                    vol_ratio = min(vol_ratio, self.risk_config.vol_max_ratio)
                    vol_ratio = max(vol_ratio, 0.3)
                    buy_ratio *= vol_ratio

                cost_rate = 1 - self.commission - self.slippage
                buy_price = price * (1 + self.slippage)
                trade_unit = self.initial_capital * buy_ratio
                cost = min(trade_unit, cash) * cost_rate
                qty = cost / buy_price

                # 更新本地状态
                position = qty
                avg_price = buy_price
                cash = cash - cost
                trade_executed = True
                is_buy = True
                traded_price = buy_price
                traded_qty = qty

            elif risk_signal == -1 and position > 0:
                # 卖出
                sell_price = price * (1 - self.slippage)
                proceeds = position * sell_price * (1 - self.commission)
                cash += proceeds
                position = 0.0
                avg_price = 0.0
                trade_executed = True
                is_buy = False
                traded_price = sell_price
                traded_qty = 0.0

            # 更新风控状态（在本地变量更新后）
            equity = cash + position * price
            if trade_executed:
                risk.on_fill(date_str, traded_price, traded_qty, is_buy, equity)

            equity = cash + position * price
            records.append({
                "date": date_str,
                "close": price,
                "position": position,
                "cash": cash,
                "equity": equity,
                "signal": signal,
                "risk_signal": risk_signal,
            })

            # 更新波动率（收盘后）
            if i > 0:
                ret = (price - df.at[i-1, "close"]) / df.at[i-1, "close"]
                risk.update_volatility(pd.Series([ret]))

        result = pd.DataFrame(records)
        result["benchmark"] = (df["close"] / df["close"].iloc[0]) * self.initial_capital

        metrics = self._calc_metrics(result)
        metrics["stop_loss_count"] = stop_loss_count
        metrics["num_trades"] = trades_count

        trades = self._extract_trades(result)

        return {
            "equity_curve": result,
            "metrics": metrics,
            "trades": trades,
            "data": data,
            "signals": signals,
        }

    def _calc_metrics(self, result: pd.DataFrame) -> dict:
        """计算绩效指标"""
        equity = result["equity"].values
        benchmark = result["benchmark"].values

        total_return = (equity[-1] - equity[0]) / equity[0]
        benchmark_return = (benchmark[-1] - benchmark[0]) / benchmark[0]

        n_days = len(result)
        annual_return = (1 + total_return) ** (252 / n_days) - 1

        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        max_drawdown = drawdown.min()

        daily_returns = np.diff(equity) / equity[:-1]
        daily_returns = np.nan_to_num(daily_returns, 0)

        if daily_returns.std() > 0:
            sharpe = np.sqrt(252) * daily_returns.mean() / daily_returns.std()
        else:
            sharpe = 0

        downside = daily_returns[daily_returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = np.sqrt(252) * daily_returns.mean() / downside.std()
        else:
            sortino = 0

        win_rate = len(daily_returns[daily_returns > 0]) / max(len(daily_returns), 1)
        calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "benchmark_return": benchmark_return,
            "excess_return": total_return - benchmark_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "win_rate": win_rate,
            "calmar_ratio": calmar,
            "final_equity": equity[-1],
        }

    def _extract_trades(self, result: pd.DataFrame) -> list:
        """提取交易记录"""
        trades = []
        pos = 0
        for i in range(len(result)):
            row = result.iloc[i]
            sig = row.get("risk_signal", 0)
            if sig == 1 and pos == 0:
                trades.append({"date": row["date"], "action": "BUY", "price": row["close"]})
                pos = 1
            elif sig == -1 and pos == 1:
                trades.append({"date": row["date"], "action": "SELL", "price": row["close"]})
                pos = 0
        return trades

    def print_report(self, result: dict, strategy_name: str = ""):
        """打印回测报告"""
        m = result["metrics"]

        print(f"\n{'='*55}")
        print(f"  回测报告(V2+风控): {strategy_name}")
        print(f"{'='*55}")
        print(f"  {'总收益率':>15}: {m['total_return']*100:>8.2f}%")
        print(f"  {'年化收益率':>15}: {m['annual_return']*100:>8.2f}%")
        print(f"  {'基准收益':>15}: {m['benchmark_return']*100:>8.2f}%")
        print(f"  {'超额收益':>15}: {m['excess_return']*100:>8.2f}%")
        print(f"  {'最大回撤':>15}: {m['max_drawdown']*100:>8.2f}%")
        print(f"  {'夏普比率':>15}: {m['sharpe_ratio']:>8.2f}")
        print(f"  {'索提诺比率':>15}: {m['sortino_ratio']:>8.2f}")
        print(f"  {'卡玛比率':>15}: {m['calmar_ratio']:>8.2f}")
        print(f"  {'胜率':>15}: {m['win_rate']*100:>8.2f}%")
        print(f"  {'交易次数':>15}: {m['num_trades']:>8}")
        print(f"  {'止损次数':>15}: {m.get('stop_loss_count', 0):>8}")
        print(f"  {'最终资金':>15}: {m['final_equity']:>10.2f}")
        print(f"{'='*55}")

        trades = result["trades"]
        if trades:
            print(f"\n最近交易:")
            for t in trades[-5:]:
                print(f"  {t['date']} {t['action']} @ {t['price']:.2f}")


if __name__ == "__main__":
    # 简单测试
    print("风控模块测试")

    cfg = PositionConfig(
        base_ratio=0.8,
        stop_loss=0.05,
        trailing_stop=True,
        trailing_pct=0.04,
        vol_adjust=False,
    )

    risk = RiskManager(cfg)

    print(f"默认配置: base_ratio={risk.config.base_ratio}, stop_loss={risk.config.stop_loss}")
    print(f"跟踪止损: {risk.config.trailing_stop}, {risk.config.trailing_pct*100}%")

    print("\n风控模块正常!")
