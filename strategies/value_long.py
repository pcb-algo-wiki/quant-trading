"""长线价值 Alpha 策略

三因子合成信号：
  - 护城河分数（financial_reports → score_moat）
  - 政策对齐分数（policy_items → PolicyAligner）
  - 情感传播分数（industry_events.propagated_score 均值）

当 DB 不可用时降级为双均线趋势过滤。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Strategy


class ValueLongStrategy(Strategy):
    """长线价值 Alpha 策略。

    composite = w_moat * moat_norm
              + w_policy * policy_score
              + w_sentiment * (avg_sentiment + 1) / 2

    composite > buy_threshold  → 跟随趋势做多
    composite < sell_threshold → 空仓
    else                       → 持有当前仓位
    """

    def __init__(
        self,
        fast: int = 20,
        slow: int = 60,
        buy_threshold: float = 0.55,
        sell_threshold: float = 0.45,
        moat_weight: float = 0.4,
        policy_weight: float = 0.3,
        sentiment_weight: float = 0.3,
        db_path: Optional[str] = None,
        symbol: str = "",
    ) -> None:
        super().__init__("ValueLong")
        self.fast = fast
        self.slow = slow
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.weights = (moat_weight, policy_weight, sentiment_weight)
        self.db_path = db_path
        self.symbol = symbol

    # ── 内部数据加载 ──────────────────────────────────────────────────────────

    def _load_scores(self, symbol: str, conn) -> tuple[float, float, float]:
        """返回 (moat_norm, policy_score, avg_sentiment) 均在 [0, 1]。"""
        moat_norm = self._load_moat(symbol, conn)
        policy_score = self._load_policy(symbol, conn)
        avg_sentiment = self._load_sentiment(symbol, conn)
        return moat_norm, policy_score, avg_sentiment

    def _load_moat(self, symbol: str, conn) -> float:
        """从 financial_reports 计算护城河分数归一到 [0, 1]。"""
        try:
            row = conn.execute(
                """SELECT revenue, net_profit, gross_margin, rd_expense
                   FROM financial_reports
                   WHERE symbol = ?
                   ORDER BY report_period DESC
                   LIMIT 1""",
                (symbol,),
            ).fetchone()
            if row is None:
                return 0.5

            from data.filings.cninfo import FinancialRecord
            from knowledge.prompts import score_moat

            rec = FinancialRecord(
                symbol=symbol,
                report_period="",
                revenue=row[0],
                net_profit=row[1],
                gross_margin=row[2],
                rd_expense=row[3],
                source="db",
            )
            result = score_moat(rec)
            return min(1.0, result["total_score"] / 5.0)
        except Exception:
            return 0.5

    def _load_policy(self, symbol: str, conn) -> float:
        """从 policy_items 计算政策对齐分。"""
        try:
            from research.policy_alignment import build_aligner_from_store

            # 用 financial_reports 的 symbol 描述（不含主营，以 symbol 为查询词）
            aligner = build_aligner_from_store(conn)
            return aligner.score(symbol)
        except Exception:
            return 0.0

    def _load_sentiment(self, symbol: str, conn) -> float:
        """从 industry_events 取 propagated_score 均值（最近 30 天）。"""
        try:
            row = conn.execute(
                """SELECT AVG(propagated_score)
                   FROM industry_events
                   WHERE (symbol = ? OR industry = ?)
                     AND propagated_score IS NOT NULL""",
                (symbol, symbol),
            ).fetchone()
            val = row[0] if row and row[0] is not None else 0.0
            return float(np.clip(val, -1.0, 1.0))
        except Exception:
            return 0.0

    # ── 信号生成 ──────────────────────────────────────────────────────────────

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy().reset_index(drop=True)

        # 基础趋势指标
        df["ma_fast"] = df["close"].rolling(self.fast, min_periods=1).mean()
        df["ma_slow"] = df["close"].rolling(self.slow, min_periods=1).mean()
        trend_up = df["ma_fast"] > df["ma_slow"]

        # 尝试加载 DB 分数
        composite = self._compute_composite()

        # 信号逻辑
        w_m, w_p, w_s = self.weights
        positions = []
        signals = []
        prev_pos = 0

        for i in range(len(df)):
            trend = int(trend_up.iloc[i])
            if composite > self.buy_threshold and trend:
                pos = 1
            elif composite < self.sell_threshold:
                pos = 0
            else:
                pos = prev_pos  # 保持

            sig = pos - prev_pos
            positions.append(pos)
            signals.append(sig)
            prev_pos = pos

        df["position"] = positions
        df["signal"] = signals
        df["composite_score"] = composite

        return df[["open", "high", "low", "close", "volume",
                   "ma_fast", "ma_slow", "position", "signal", "composite_score"]]

    def _compute_composite(self) -> float:
        """连接 DB 计算复合分数；失败降级为中性 0.5。"""
        if not self.db_path and not self.symbol:
            return 0.5

        conn = None
        try:
            if self.db_path:
                import sqlite3
                conn = sqlite3.connect(self.db_path)
            else:
                from data_store.db import get_connection
                conn = get_connection()

            moat, policy, sent = self._load_scores(self.symbol, conn)
            w_m, w_p, w_s = self.weights
            composite = w_m * moat + w_p * policy + w_s * ((sent + 1) / 2)
            return float(np.clip(composite, 0.0, 1.0))
        except Exception:
            return 0.5
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
