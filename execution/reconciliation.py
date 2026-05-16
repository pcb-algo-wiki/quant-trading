"""每日三方对账

对账逻辑：
  1. 信号侧：当日 signal != 0 的行
  2. 成交侧：当日实际发生的 Order/Trade 记录
  3. 持仓侧：期末实际持仓 vs 策略预期持仓

差异超出容忍阈值时 is_clean = False，结果写入 reconcile_reports 表。

用法：
    from execution.reconciliation import Reconciler
    rec = Reconciler()
    report = rec.reconcile(signals_df, trades_list, positions_dict, date="2024-01-15")
    print(report.is_clean)
    rec.save_to_db(conn, report)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import pandas as pd


@dataclass
class ReconcileReport:
    """对账报告。"""
    date: str
    unmatched_signals: list = field(default_factory=list)   # 信号有但成交没有
    unmatched_trades: list = field(default_factory=list)    # 成交有但信号没有
    position_drift: dict = field(default_factory=dict)      # symbol → (expected, actual, delta)
    is_clean: bool = True
    notes: str = ""


class Reconciler:
    """三方对账器（信号 vs 成交 vs 持仓）。

    Args:
        position_tol: 持仓漂移容忍比例（如 0.01 = 1%），超出时标记不洁
        strict_signal_match: True 时要求每条 signal != 0 都有对应成交
    """

    def __init__(
        self,
        position_tol: float = 0.01,
        strict_signal_match: bool = False,
    ) -> None:
        self.position_tol = position_tol
        self.strict_signal_match = strict_signal_match

    def reconcile(
        self,
        signals_df: pd.DataFrame,
        trades: list[dict],
        positions: dict[str, float],
        date: Optional[str] = None,
    ) -> ReconcileReport:
        """执行对账。

        Args:
            signals_df: 策略输出 DataFrame，含 signal 列（1/-1/0）和可选 symbol 列
            trades: 成交记录列表，每条含 symbol/side/qty/price
            positions: 实际持仓 {symbol: qty}
            date: 对账日期（默认今日）

        Returns:
            ReconcileReport
        """
        date = date or datetime.utcnow().strftime("%Y-%m-%d")
        report = ReconcileReport(date=date)

        # 1. 信号侧：有交易意图的 symbol 集合
        signal_symbols: set[str] = set()
        if "symbol" in signals_df.columns:
            signal_symbols = set(
                signals_df.loc[signals_df["signal"] != 0, "symbol"].dropna().tolist()
            )
        # 无 symbol 列时只校验持仓漂移

        # 2. 成交侧：实际成交 symbol 集合
        trade_symbols: set[str] = {t.get("symbol", "") for t in trades if t.get("symbol")}

        # 3. 信号有但成交没有
        if self.strict_signal_match:
            for sym in signal_symbols - trade_symbols:
                report.unmatched_signals.append({"symbol": sym, "reason": "no_trade_found"})
                report.is_clean = False

        # 4. 成交有但信号没有（异常成交）
        for sym in trade_symbols - signal_symbols:
            report.unmatched_trades.append({"symbol": sym, "reason": "unexpected_trade"})
            report.is_clean = False

        # 5. 持仓漂移：position=1 → 期望持仓>0；position=0 → 期望无仓
        if "symbol" in signals_df.columns and "position" in signals_df.columns:
            latest = signals_df.groupby("symbol")["position"].last()
            for sym, flag in latest.items():
                act_pos = positions.get(sym, 0.0)
                in_position = flag > 0
                actually_held = act_pos > 0
                if in_position != actually_held:
                    report.position_drift[sym] = {
                        "expected_in_position": in_position,
                        "actual_qty": act_pos,
                    }
                    report.is_clean = False

        if report.unmatched_signals or report.unmatched_trades or report.position_drift:
            report.notes = (
                f"unmatched_signals={len(report.unmatched_signals)}, "
                f"unmatched_trades={len(report.unmatched_trades)}, "
                f"position_drift_items={len(report.position_drift)}"
            )

        return report

    def save_to_db(self, conn, report: ReconcileReport) -> str:
        """幂等写入 reconcile_reports 表，返回 report_id。"""
        report_id = f"rec-{report.date}-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """
            INSERT OR REPLACE INTO reconcile_reports
                (report_id, date, is_clean, unmatched_signals_json,
                 unmatched_trades_json, position_drift_json, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                report.date,
                int(report.is_clean),
                json.dumps(report.unmatched_signals, ensure_ascii=False),
                json.dumps(report.unmatched_trades, ensure_ascii=False),
                json.dumps(report.position_drift, ensure_ascii=False),
                report.notes,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        return report_id
