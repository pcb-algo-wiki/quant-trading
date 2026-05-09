"""
专业回测引擎
- 支持做多/做空/做空止损
- 计算完整风险指标
- 支持Walk-forward验证
"""

import pandas as pd
import numpy as np
from typing import Optional, List, Tuple
from pathlib import Path
import json


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 100_000,
        commission: float = 0.0003,
        slippage: float = 0.0001,
        position_ratio: float = 1.0,
    ):
        """
        Args:
            initial_capital: 初始资金
            commission: 手续费率（印花税+佣金）
            slippage: 滑点（按价格比例）
            position_ratio: 仓位比例（可融资时>1）
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.position_ratio = position_ratio

    def run(
        self,
        data: pd.DataFrame,
        signals: pd.DataFrame,
    ) -> dict:
        """
        运行回测

        Args:
            data: 原始OHLCV数据
            signals: 策略信号（包含signal, position列）

        Returns:
            回测结果字典
        """
        df = data.copy().reset_index(drop=True)
        sig = signals.copy().reset_index(drop=True)

        # 合并信号
        for col in sig.columns:
            if col not in df.columns:
                df[col] = sig[col]

        # 初始化
        cash = self.initial_capital
        position = 0.0   # 持股数量
        trade_unit = self.initial_capital * self.position_ratio  # 每笔交易金额

        records = []

        for i in range(len(df)):
            price = df.at[i, "close"]
            signal = int(df.at[i, "signal"]) if "signal" in df.columns else 0

            # 交易成本
            cost_rate = 1 - self.commission - self.slippage

            if signal == 1 and cash >= trade_unit * 0.5:  # 买入（信号1=金叉买入）
                buy_price = price * (1 + self.slippage)
                cost = min(trade_unit, cash) * cost_rate
                position = cost / buy_price
                cash = cash - cost
                # cash已扣除手续费，position为持股数

            elif signal == -1 and position > 0:  # 卖出（信号-1=死叉卖出）
                sell_price = price * (1 - self.slippage)
                proceeds = position * sell_price * cost_rate
                cash += proceeds
                position = 0.0

            # 当日权益
            equity = cash + position * price
            records.append({
                "date": df.at[i, "date"] if "date" in df.columns else i,
                "close": price,
                "position": position,
                "cash": cash,
                "equity": equity,
            })

        # 构建结果DataFrame
        result = pd.DataFrame(records)
        if len(result) == 0:
            return {
                "equity_curve": result,
                "metrics": {k: 0 for k in ["total_return","annual_return","benchmark_return",
                          "excess_return","max_drawdown","sharpe_ratio","sortino_ratio",
                          "win_rate","calmar_ratio","num_trades","final_equity"]},
                "trades": [],
                "data": data,
                "signals": signals,
            }
        result["benchmark"] = (df["close"] / df["close"].iloc[0]) * self.initial_capital

        # 计算绩效指标
        metrics = self._calc_metrics(result)

        # 实际交易次数：用signal变化次数
        num_trades = int((sig["signal"].abs() > 0).sum())
        metrics["num_trades"] = num_trades

        # 提取交易记录
        trades = self._extract_trades(df, sig)

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

        # 总收益
        total_return = (equity[-1] - equity[0]) / equity[0]
        benchmark_return = (benchmark[-1] - benchmark[0]) / benchmark[0]

        # 年化收益
        n_days = len(result)
        annual_return = (1 + total_return) ** (252 / n_days) - 1

        # 最大回撤
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        max_drawdown = drawdown.min()

        # 日收益
        daily_returns = np.diff(equity) / equity[:-1]
        daily_returns = np.nan_to_num(daily_returns, 0)

        # 夏普比率
        if daily_returns.std() > 0:
            sharpe = np.sqrt(252) * daily_returns.mean() / daily_returns.std()
        else:
            sharpe = 0

        # 索提诺比率（只算下行波动）
        downside = daily_returns[daily_returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = np.sqrt(252) * daily_returns.mean() / downside.std()
        else:
            sortino = 0

        # 胜率
        win_rate = len(daily_returns[daily_returns > 0]) / max(len(daily_returns), 1)

        # 卡玛比率
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
            "num_trades": 0,  # computed in run()
            "final_equity": equity[-1],
        }

    def _extract_trades(self, data: pd.DataFrame, signals: pd.DataFrame) -> List[dict]:
        """提取交易记录"""
        trades = []
        sig = signals.copy().reset_index(drop=True)
        dat = data.copy().reset_index(drop=True)

        pos = 0
        for i in range(len(sig)):
            if sig.at[i, "signal"] == 1 and pos == 0:  # 买入
                trades.append({
                    "date": dat.at[i, "date"] if "date" in dat.columns else i,
                    "action": "BUY",
                    "price": dat.at[i, "close"],
                })
                pos = 1
            elif sig.at[i, "signal"] == -1 and pos == 1:  # 卖出
                trades.append({
                    "date": dat.at[i, "date"] if "date" in dat.columns else i,
                    "action": "SELL",
                    "price": dat.at[i, "close"],
                })
                pos = 0
        return trades

    def walk_forward(
        self,
        data: pd.DataFrame,
        signals: pd.DataFrame,
        train_window: int = 252,
        test_window: int = 63,
    ) -> List[dict]:
        """
        Walk-forward分析

        Args:
            data: 数据
            signals: 信号
            train_window: 训练窗口（天数）
            test_window: 测试窗口（天数）
        """
        results = []
        n = len(data)

        for start in range(0, n - test_window, test_window):
            train_end = start + train_window
            test_end = min(start + train_window + test_window, n)

            if train_end > n:
                break

            train_data = data.iloc[start:train_end]
            test_data = data.iloc[train_end:test_end]

            # 只用训练数据跑回测，获取参数
            train_signals = signals.iloc[start:train_end]

            # 测试集信号
            test_signals = signals.iloc[train_end:test_end]

            result = self.run(test_data, test_signals)

            results.append({
                "train_start": start,
                "train_end": train_end,
                "test_start": train_end,
                "test_end": test_end,
                "metrics": result["metrics"],
            })

        return results

    def print_report(self, result: dict, strategy_name: str = ""):
        """打印回测报告"""
        m = result["metrics"]
        eq = result["equity_curve"]

        print(f"\n{'='*55}")
        print(f"  回测报告: {strategy_name}")
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
        print(f"  {'最终资金':>15}: {m['final_equity']:>10.2f}")
        print(f"{'='*55}")

        # 最近5笔交易
        trades = result["trades"]
        if trades:
            print(f"\n最近交易:")
            for t in trades[-5:]:
                print(f"  {t['date']} {t['action']} @ {t['price']:.2f}")
