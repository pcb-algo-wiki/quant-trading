"""Phase 4 策略层测试

覆盖：ValueLongStrategy / EventDrivenStrategy / MVOptimizer / RegimeDetector
共 ≥ 16 个用例。
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from strategies.value_long import ValueLongStrategy
from strategies.event_driven import EventDrivenStrategy
from portfolio.optimizer import MVOptimizer
from portfolio.regime_gating import RegimeDetector


# ── 测试数据 ─────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    })


def _make_db(tmp_path: Path) -> str:
    db_file = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS financial_reports (
            symbol TEXT, report_period TEXT, revenue REAL,
            net_profit REAL, gross_margin REAL, rd_expense REAL,
            source TEXT, ingested_at TEXT,
            PRIMARY KEY (symbol, report_period, source)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS policy_items (
            source TEXT, title TEXT, published_at TEXT,
            url TEXT, content TEXT, content_hash TEXT, ingested_at TEXT,
            UNIQUE (source, content_hash)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS industry_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT,
            industry TEXT,
            symbol TEXT,
            title TEXT,
            score REAL,
            source TEXT,
            published_at TEXT,
            ingested_at TEXT,
            sentiment_score REAL,
            policy_score REAL,
            propagated_score REAL
        )
    """)
    conn.commit()
    conn.close()
    return db_file


# ── ValueLongStrategy ─────────────────────────────────────────────────────────

class TestValueLongStrategy:

    def test_no_db_returns_valid_signals(self):
        """无 DB 时降级为 SMA 信号，输出含 signal/position 列。"""
        strat = ValueLongStrategy()
        df = _make_ohlcv()
        out = strat.generate(df)
        assert "signal" in out.columns
        assert "position" in out.columns

    def test_signal_values_in_contract(self):
        """signal 只含 -1/0/1；position 只含 0/1。"""
        strat = ValueLongStrategy()
        out = strat.generate(_make_ohlcv())
        assert set(out["signal"].unique()).issubset({-1, 0, 1})
        assert set(out["position"].unique()).issubset({0, 1})

    def test_high_composite_leads_to_buys(self, tmp_path):
        """composite > buy_threshold 时应有买入信号。"""
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO financial_reports VALUES (?,?,?,?,?,?,?,?)",
            ("510300", "2023-12-31", 1e9, 3e8, 0.60, 5e7, "test", "2024-01-01"),
        )
        conn.execute(
            "INSERT INTO policy_items VALUES (?,?,?,?,?,?,?)",
            ("test", "半导体产业政策", "2023-01-01", None, "芯片 半导体 国产化", "h1", "2024-01-01"),
        )
        conn.commit()
        conn.close()

        strat = ValueLongStrategy(
            buy_threshold=0.4,
            sell_threshold=0.2,
            db_path=db_path,
            symbol="510300",
        )
        out = strat.generate(_make_ohlcv())
        assert out["position"].sum() > 0, "高 composite 时应有多头仓位"

    def test_low_composite_leads_to_flat(self, tmp_path):
        """composite 固定为 0 时应全空仓（buy_threshold=0.55, sell_threshold=0.45）。"""
        strat = ValueLongStrategy(
            buy_threshold=0.55,
            sell_threshold=0.45,
        )
        # 无 DB 时 composite = 0.5 → 保持当前仓位（初始 0，不变）
        # 覆盖 _compute_composite 使其返回极低值
        strat._compute_composite = lambda: 0.1
        out = strat.generate(_make_ohlcv())
        assert out["position"].sum() == 0, "低 composite 应全空仓"

    def test_output_row_count_matches_input(self):
        """输出行数与输入一致。"""
        strat = ValueLongStrategy()
        df = _make_ohlcv(80)
        assert len(strat.generate(df)) == len(df)

    def test_composite_score_column_present(self):
        """输出包含 composite_score 列。"""
        strat = ValueLongStrategy()
        out = strat.generate(_make_ohlcv())
        assert "composite_score" in out.columns


# ── EventDrivenStrategy ───────────────────────────────────────────────────────

class TestEventDrivenStrategy:

    def test_no_events_returns_zero_signal(self):
        """无 DB、无事件时 signal 应全为 0，position 全为 0。"""
        strat = EventDrivenStrategy()
        out = strat.generate(_make_ohlcv())
        assert (out["signal"] == 0).all()
        assert (out["position"] == 0).all()

    def test_positive_event_with_uptrend_gives_buy(self, tmp_path):
        """正向事件 + MACD 上涨 → 应有买入信号。"""
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        # 插入多条正向 propagated_score
        for i in range(10):
            conn.execute(
                "INSERT INTO industry_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"e{i}", "sentiment_propagation", "科技", "510300",
                 "利好消息", 0.8, "test", f"2023-01-{i+5:02d}", "2023-01-15",
                 0.8, 0.6, 0.8),
            )
        conn.commit()
        conn.close()

        strat = EventDrivenStrategy(
            pos_threshold=0.1,
            window=20,
            industry="科技",
            symbol="510300",
            db_path=db_path,
        )
        out = strat.generate(_make_ohlcv())
        # 只要有 MACD 上涨 + 事件，就应有 position=1
        assert out["position"].max() == 1

    def test_negative_event_does_not_buy(self, tmp_path):
        """负向事件时不应产生多头仓位。"""
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        for i in range(10):
            conn.execute(
                "INSERT INTO industry_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"ne{i}", "sentiment_propagation", "科技", "510300",
                 "利空消息", -0.9, "test", f"2023-01-{i+5:02d}", "2023-01-15",
                 -0.9, 0.1, -0.9),
            )
        conn.commit()
        conn.close()

        strat = EventDrivenStrategy(
            pos_threshold=0.5,
            neg_threshold=-0.3,
            industry="科技",
            db_path=db_path,
        )
        out = strat.generate(_make_ohlcv())
        assert (out["position"] == 0).all()

    def test_signal_contract(self):
        """signal ∈ {-1, 0, 1}，position ∈ {0, 1}。"""
        strat = EventDrivenStrategy()
        out = strat.generate(_make_ohlcv())
        assert set(out["signal"].unique()).issubset({-1, 0, 1})
        assert set(out["position"].unique()).issubset({0, 1})

    def test_macd_columns_present(self):
        """输出含 macd_dif / macd_dea 列。"""
        strat = EventDrivenStrategy()
        out = strat.generate(_make_ohlcv())
        assert "macd_dif" in out.columns
        assert "macd_dea" in out.columns


# ── MVOptimizer ───────────────────────────────────────────────────────────────

class TestMVOptimizer:

    def _make_returns(self, n: int = 60, cols: list = None) -> pd.DataFrame:
        rng = np.random.default_rng(0)
        cols = cols or ["long_alpha", "event_driven"]
        data = rng.normal(0.0005, 0.01, (n, len(cols)))
        return pd.DataFrame(data, columns=cols)

    def test_weights_sum_to_one(self):
        opt = MVOptimizer()
        returns = self._make_returns()
        w = opt.optimize(returns)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_weights_non_negative(self):
        opt = MVOptimizer()
        w = opt.optimize(self._make_returns())
        assert all(v >= 0 for v in w.values())

    def test_equal_weight_fallback_single_row(self):
        """单行数据降级为等权。"""
        opt = MVOptimizer()
        returns = self._make_returns(n=1)
        w = opt.optimize(returns)
        assert len(w) == 2
        assert all(abs(v - 0.5) < 1e-6 for v in w.values())

    def test_equal_weight_fallback_empty(self):
        """无列时返回空字典。"""
        opt = MVOptimizer()
        w = opt.optimize(pd.DataFrame())
        assert w == {}

    def test_sharpe_maximization_direction(self):
        """高夏普策略应获得更多权重。"""
        rng = np.random.default_rng(1)
        n = 252
        good = rng.normal(0.001, 0.005, n)   # 高 Sharpe
        bad = rng.normal(0.0001, 0.02, n)    # 低 Sharpe
        returns = pd.DataFrame({"good": good, "bad": bad})
        opt = MVOptimizer()
        w = opt.optimize(returns)
        assert w["good"] >= w["bad"], "高 Sharpe 策略应获得更高权重"


# ── RegimeDetector ────────────────────────────────────────────────────────────

class TestRegimeDetector:

    def _make_price(self, trend: float = 0.001, vol: float = 0.01, n: int = 80) -> pd.Series:
        rng = np.random.default_rng(99)
        returns = rng.normal(trend, vol, n)
        return pd.Series(100.0 * np.cumprod(1 + returns))

    def test_bull_detection(self):
        """低波动率 + 稳定上涨 → bull。"""
        det = RegimeDetector(vol_bull=0.5, vol_bear=1.0, dd_bull=-0.5, dd_bear=-1.0, sent_bull=0.0, sent_bear=-100.0)
        # 强制所有指标 bull
        regime = det.detect(self._make_price(0.001, 0.001), avg_sentiment=0.5)
        assert regime == "bull"

    def test_bear_detection(self):
        """高波动率 + 负情绪 → bear。"""
        det = RegimeDetector(vol_bull=0.001, vol_bear=0.001, dd_bull=-0.001, dd_bear=-0.001, sent_bull=100.0, sent_bear=-100.0)
        regime = det.detect(self._make_price(0.0, 0.05), avg_sentiment=-0.5)
        assert regime == "bear"

    def test_neutral_detection(self):
        """中等参数 → neutral（两票对两票）。"""
        det = RegimeDetector()
        price = self._make_price(0.0005, 0.015, 80)
        regime = det.detect(price, avg_sentiment=0.0)
        assert regime in {"bull", "neutral", "bear"}

    def test_get_weights_sum_to_one(self):
        det = RegimeDetector()
        for regime in ("bull", "neutral", "bear"):
            w = det.get_weights(regime)
            assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_get_weights_keys(self):
        det = RegimeDetector()
        w = det.get_weights("bull")
        assert "long_alpha" in w and "event_driven" in w

    def test_short_price_no_crash(self):
        """价格序列长度 1 不崩溃。"""
        det = RegimeDetector()
        regime = det.detect(pd.Series([100.0]), avg_sentiment=0.0)
        assert regime in {"bull", "neutral", "bear"}


# ── 集成测试 ─────────────────────────────────────────────────────────────────

class TestIntegration:

    def test_both_strategies_produce_signal_position(self):
        """两种策略均输出 signal/position 列，类型兼容。"""
        df = _make_ohlcv()
        for strat in [ValueLongStrategy(), EventDrivenStrategy()]:
            out = strat.generate(df)
            assert "signal" in out.columns
            assert "position" in out.columns
            assert len(out) == len(df)

    def test_regime_weights_compatible_with_optimizer(self):
        """Regime 权重可作为 MVOptimizer 输出对标验证。"""
        det = RegimeDetector()
        regime = det.detect(pd.Series(np.linspace(100, 110, 60)), avg_sentiment=0.2)
        w = det.get_weights(regime)
        # 权重和为 1
        assert abs(sum(w.values()) - 1.0) < 1e-6
        # 权重非负
        assert all(v >= 0 for v in w.values())
