"""Vectorbt 回测引擎封装（Phase 7）

软导入 vectorbt：
  - 有包 → VectorbtEngine.run() 使用 vectorbt 计算指标（更快/更精确）
  - 无包 → 自动降级为 backtest.engine.BacktestEngine

接口与现有 BacktestEngine 完全一致：
    result = VectorbtEngine(initial_capital=100_000).run(data_df, signals_df)
    result["metrics"]  # 同样包含 total_return/sharpe_ratio/max_drawdown 等

用法：
    from backtest.vectorbt_engine import VectorbtEngine
    eng = VectorbtEngine(initial_capital=100_000)
    result = eng.run(data_df, signals_df)
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _vectorbt_available() -> bool:
    try:
        import vectorbt  # noqa: F401
        return True
    except ImportError:
        return False


class VectorbtEngine:
    """Vectorbt 加速回测引擎（Phase 7），无包时自动降级。

    Args:
        initial_capital: 初始资金
        commission: 手续费（单边比例）
        slippage: 滑点（单边比例）
        prefer_vbt: True 时优先使用 vectorbt；False 时直接用基线引擎
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        commission: float = 0.0003,
        slippage: float = 0.0001,
        prefer_vbt: bool = True,
    ) -> None:
        self.initial_capital = float(initial_capital)
        self.commission = float(commission)
        self.slippage = float(slippage)
        self._use_vbt = prefer_vbt and _vectorbt_available()
        if prefer_vbt and not self._use_vbt:
            logger.info("[VectorbtEngine] vectorbt 未安装，降级为 BacktestEngine")

    @property
    def using_vectorbt(self) -> bool:
        return self._use_vbt

    def run(self, data: pd.DataFrame, signals: pd.DataFrame) -> dict:
        """执行回测，返回与 BacktestEngine 一致的 result dict。

        Args:
            data: OHLCV DataFrame（含 close 列）
            signals: 策略信号 DataFrame（含 signal 和 position 列）

        Returns:
            {
              "equity_curve": pd.Series,
              "metrics": {total_return, annual_return, max_drawdown, sharpe_ratio, num_trades},
              "trades": list[dict],
              "engine": "vectorbt" | "baseline",
            }
        """
        if self._use_vbt:
            return self._run_vbt(data, signals)
        return self._run_baseline(data, signals)

    def _run_vbt(self, data: pd.DataFrame, signals: pd.DataFrame) -> dict:
        try:
            import vectorbt as vbt

            close = data["close"]
            entries = signals.get("position", pd.Series(0, index=data.index)).shift(1).fillna(0)
            entries = (entries > 0) & (entries.shift(1).fillna(0) == 0)
            exits   = signals.get("position", pd.Series(0, index=data.index)).shift(1).fillna(0)
            exits   = (exits == 0) & (exits.shift(1).fillna(0) > 0)

            pf = vbt.Portfolio.from_signals(
                close=close,
                entries=entries,
                exits=exits,
                init_cash=self.initial_capital,
                fees=self.commission + self.slippage,
            )

            equity = pf.value()
            total_return = float((equity.iloc[-1] / equity.iloc[0]) - 1)
            n_days = len(equity)
            annual_return = float((1 + total_return) ** (252 / max(n_days, 1)) - 1)
            dd = (equity / equity.cummax() - 1)
            max_drawdown = float(dd.min())
            daily_ret = equity.pct_change().dropna()
            sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0

            return {
                "equity_curve": equity,
                "metrics": {
                    "total_return": total_return,
                    "annual_return": annual_return,
                    "max_drawdown": max_drawdown,
                    "sharpe_ratio": sharpe,
                    "num_trades": int(pf.trades.count()),
                },
                "trades": [],
                "engine": "vectorbt",
            }
        except Exception as exc:
            logger.warning("[VectorbtEngine] vectorbt 运行失败: %s，降级为 BacktestEngine", exc)
            return self._run_baseline(data, signals)

    def _run_baseline(self, data: pd.DataFrame, signals: pd.DataFrame) -> dict:
        from backtest.engine import BacktestEngine
        result = BacktestEngine(
            initial_capital=self.initial_capital,
            commission=self.commission,
            slippage=self.slippage,
        ).run(data, signals)
        result["engine"] = "baseline"
        return result
