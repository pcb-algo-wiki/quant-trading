"""事件驱动短线策略

消费 industry_events.propagated_score（Phase 3 传播输出），
结合 MACD 趋势确认，生成短线信号。

当 DB 不可用时退化为纯 MACD 策略。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Strategy


class EventDrivenStrategy(Strategy):
    """事件驱动策略。

    事件分逻辑：
        event_score = mean(propagated_score) of recent window days
        if event_score > pos_threshold AND MACD bullish → signal = 1
        elif event_score < neg_threshold AND MACD bearish → signal = -1
        else → signal = 0
    """

    def __init__(
        self,
        window: int = 7,
        pos_threshold: float = 0.2,
        neg_threshold: float = -0.2,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        industry: Optional[str] = None,
        symbol: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> None:
        super().__init__("EventDriven")
        self.window = window
        self.pos_threshold = pos_threshold
        self.neg_threshold = neg_threshold
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal_period = macd_signal
        self.industry = industry
        self.symbol = symbol
        self.db_path = db_path

    # ── 数据加载 ──────────────────────────────────────────────────────────────

    def _get_propagated_scores(
        self, dates: list[str], conn
    ) -> pd.Series:
        """按日期返回 propagated_score 均值 Series，缺失填 0。"""
        if conn is None:
            return pd.Series(0.0, index=range(len(dates)))

        filters = []
        params: list = []
        if self.industry:
            filters.append("industry = ?")
            params.append(self.industry)
        if self.symbol:
            filters.append("symbol = ?")
            params.append(self.symbol)

        where = f"WHERE ({' OR '.join(filters)})" if filters else ""
        query = f"""
            SELECT date(published_at) as day, AVG(propagated_score) as avg_score
            FROM industry_events
            {where}
            GROUP BY day
        """
        try:
            rows = conn.execute(query, params).fetchall()
        except Exception:
            rows = []

        score_map: dict[str, float] = {r[0]: r[1] for r in rows if r[1] is not None}

        # 将日期对齐到 DataFrame 索引
        scores = []
        for date in dates:
            date_str = str(date)[:10]
            # 取窗口内均值
            window_scores = [
                score_map[d]
                for d in score_map
                if d <= date_str
            ][-self.window :]
            scores.append(float(np.mean(window_scores)) if window_scores else 0.0)

        return pd.Series(scores, dtype=float)

    def _open_conn(self):
        """打开 DB 连接，失败返回 None。"""
        try:
            if self.db_path:
                import sqlite3
                return sqlite3.connect(self.db_path)
            from data_store.db import get_connection
            return get_connection()
        except Exception:
            return None

    # ── 信号生成 ──────────────────────────────────────────────────────────────

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy().reset_index(drop=True)

        # MACD 计算
        ema_fast = df["close"].ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.macd_slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.macd_signal_period, adjust=False).mean()
        df["macd_dif"] = dif
        df["macd_dea"] = dea
        macd_bullish = dif > dea
        macd_bearish = dif < dea

        # 事件分数加载
        dates = df["date"].tolist() if "date" in df.columns else [None] * len(df)
        conn = self._open_conn()
        try:
            event_scores = self._get_propagated_scores(
                [str(d)[:10] if d is not None else "" for d in dates], conn
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        df["event_score"] = event_scores.values

        # 信号逻辑
        positions = []
        signals = []
        prev_pos = 0

        for i in range(len(df)):
            escore = df["event_score"].iloc[i]
            bull = bool(macd_bullish.iloc[i])
            bear = bool(macd_bearish.iloc[i])

            if escore > self.pos_threshold and bull:
                pos = 1
            elif escore < self.neg_threshold and bear:
                pos = 0
            else:
                pos = prev_pos

            sig = pos - prev_pos
            positions.append(pos)
            signals.append(sig)
            prev_pos = pos

        df["position"] = positions
        df["signal"] = signals

        return df[["open", "high", "low", "close", "volume",
                   "macd_dif", "macd_dea", "event_score", "position", "signal"]]
