"""Phase 5 执行链路与数据底座测试

覆盖：
  - DataRouter: A股/美股路由，提供者不可用跳过，全失败 RuntimeError
  - DataProvider: is_available() 无包时返回 False
  - VeighNaBrokerAdapter: dry_run place/cancel/get_order/get_account/get_positions
  - LiveGuard 扩展: whitelist/blacklist/notional/daily_order 四项检查
  - Reconciler: 有差异 is_clean=False，无差异 is_clean=True，save_to_db 幂等
"""
from __future__ import annotations

import sqlite3
import types
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ─────────────────────────────────────────────────────────────────────────────
# DataRouter / DataProvider
# ─────────────────────────────────────────────────────────────────────────────

class TestDataProviderBase:
    """data/providers/base.py DataProvider ABC 不能直接实例化。"""

    def test_cannot_instantiate_abc(self):
        from data.providers.base import DataProvider
        with pytest.raises(TypeError):
            DataProvider()  # type: ignore[abstract]

    def test_abc_has_required_methods(self):
        from data.providers.base import DataProvider
        for method in ("get_name", "fetch_ohlcv", "is_available"):
            assert hasattr(DataProvider, method)


class TestSinaProvider:
    def test_is_available_returns_bool(self):
        from data.providers.sina import SinaProvider
        p = SinaProvider()
        result = p.is_available()
        assert isinstance(result, bool)

    def test_get_name(self):
        from data.providers.sina import SinaProvider
        assert SinaProvider().get_name() == "sina"


class TestAkShareProvider:
    def test_is_available_false_when_no_akshare(self, monkeypatch):
        """模拟 akshare 未安装时 is_available() 返回 False。"""
        monkeypatch.setitem(sys.modules, "akshare", None)
        # 强制重新导入以触发软导入逻辑
        import importlib
        import data.providers.akshare_provider as m
        importlib.reload(m)
        p = m.AkShareProvider()
        # akshare = None → is_available 应返回 False
        assert p.is_available() is False

    def test_get_name(self):
        from data.providers.akshare_provider import AkShareProvider
        assert AkShareProvider().get_name() == "akshare"


class TestTushareProvider:
    def test_is_available_false_when_no_token(self):
        from data.providers.tushare_provider import TushareProvider
        p = TushareProvider(token="")
        assert p.is_available() is False

    def test_get_name(self):
        from data.providers.tushare_provider import TushareProvider
        assert TushareProvider().get_name() == "tushare"


class TestPolygonProvider:
    def test_is_available_false_when_no_key(self, monkeypatch):
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        from data.providers.polygon_provider import PolygonProvider
        p = PolygonProvider(api_key="")
        assert p.is_available() is False

    def test_get_name(self):
        from data.providers.polygon_provider import PolygonProvider
        assert PolygonProvider().get_name() == "polygon"


class TestYFinanceProvider:
    def test_get_name(self):
        from data.providers.polygon_provider import YFinanceProvider
        assert YFinanceProvider().get_name() == "yfinance"

    def test_is_available_returns_bool(self):
        from data.providers.polygon_provider import YFinanceProvider
        result = YFinanceProvider().is_available()
        assert isinstance(result, bool)


class TestDataRouter:
    """DataRouter 路由逻辑。"""

    def _make_mock_provider(self, name: str, available: bool, data: pd.DataFrame | None = None):
        from data.providers.base import DataProvider
        m = MagicMock(spec=DataProvider)
        m.get_name.return_value = name
        m.is_available.return_value = available
        m.fetch_ohlcv.return_value = data if data is not None else pd.DataFrame()
        return m

    def _sample_df(self):
        return pd.DataFrame({"close": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))

    def test_a_share_routes_to_first_available(self):
        from data.providers.router import DataRouter
        sina = self._make_mock_provider("sina", True, self._sample_df())
        ak = self._make_mock_provider("akshare", True, self._sample_df())
        router = DataRouter(a_share_chain=[sina, ak], us_chain=[])
        df = router.fetch_ohlcv("510300", "20240101", "20240110")
        assert not df.empty
        sina.fetch_ohlcv.assert_called_once()
        ak.fetch_ohlcv.assert_not_called()

    def test_a_share_falls_back_when_first_unavailable(self):
        from data.providers.router import DataRouter
        sina = self._make_mock_provider("sina", False)
        ak = self._make_mock_provider("akshare", True, self._sample_df())
        router = DataRouter(a_share_chain=[sina, ak], us_chain=[])
        df = router.fetch_ohlcv("510300", "20240101", "20240110")
        assert not df.empty
        ak.fetch_ohlcv.assert_called_once()

    def test_us_symbol_routes_to_us_chain(self):
        from data.providers.router import DataRouter
        poly = self._make_mock_provider("polygon", True, self._sample_df())
        router = DataRouter(a_share_chain=[], us_chain=[poly])
        df = router.fetch_ohlcv("AAPL", "20240101", "20240110")
        assert not df.empty
        poly.fetch_ohlcv.assert_called_once()

    def test_all_failed_raises_runtime_error(self):
        from data.providers.router import DataRouter
        p1 = self._make_mock_provider("sina", True, pd.DataFrame())   # 返回空 DF
        p2 = self._make_mock_provider("akshare", True, pd.DataFrame())
        router = DataRouter(a_share_chain=[p1, p2], us_chain=[])
        with pytest.raises(RuntimeError, match="no provider"):
            router.fetch_ohlcv("510300", "20240101", "20240110")

    def test_unavailable_provider_skipped(self):
        from data.providers.router import DataRouter
        unavail = self._make_mock_provider("sina", False)
        avail = self._make_mock_provider("akshare", True, self._sample_df())
        router = DataRouter(a_share_chain=[unavail, avail], us_chain=[])
        df = router.fetch_ohlcv("510300", "20240101", "20240110")
        unavail.fetch_ohlcv.assert_not_called()
        assert not df.empty


# ─────────────────────────────────────────────────────────────────────────────
# VeighNaBrokerAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TestVeighNaBrokerAdapter:
    def _broker(self, cash: float = 100_000.0):
        from execution.broker_veighna import VeighNaBrokerAdapter
        return VeighNaBrokerAdapter(dry_run=True, initial_cash=cash)

    def test_dry_run_false_raises(self):
        from execution.broker_veighna import VeighNaBrokerAdapter
        with pytest.raises(ValueError, match="dry_run=False"):
            VeighNaBrokerAdapter(dry_run=False)

    def test_place_order_returns_standard_format(self):
        broker = self._broker()
        order = broker.place_order("510300", "BUY", 4.50, 1000)
        assert "broker_order_id" in order
        assert "status" in order
        assert "fill_price" in order
        assert order["gateway"] == "veighna_dry_run"

    def test_place_order_buy_accepted(self):
        broker = self._broker(cash=100_000)
        order = broker.place_order("510300", "BUY", 4.50, 100)
        assert order["status"] == "accepted"
        assert order["fill_qty"] == 100.0

    def test_place_order_buy_rejected_insufficient_funds(self):
        broker = self._broker(cash=100)
        order = broker.place_order("510300", "BUY", 4.50, 100_000)
        assert order["status"] == "rejected"
        assert order["fill_qty"] == 0.0

    def test_place_order_sell(self):
        broker = self._broker()
        broker.place_order("510300", "BUY", 4.50, 1000)
        order = broker.place_order("510300", "SELL", 5.00, 500)
        assert order["status"] == "accepted"

    def test_cancel_order(self):
        broker = self._broker()
        order = broker.place_order("510300", "BUY", 4.50, 100)
        result = broker.cancel_order(order["broker_order_id"])
        assert result is True
        assert broker.get_order(order["broker_order_id"])["status"] == "cancelled"

    def test_cancel_nonexistent_order(self):
        broker = self._broker()
        assert broker.cancel_order("nonexistent") is False

    def test_get_account_returns_dict(self):
        broker = self._broker(cash=50_000)
        account = broker.get_account()
        assert "cash" in account
        assert account["gateway"] == "veighna_dry_run"

    def test_get_positions_after_buy(self):
        broker = self._broker()
        broker.place_order("510300", "BUY", 4.50, 1000)
        positions = broker.get_positions()
        assert "510300" in positions
        assert positions["510300"] == 1000.0

    def test_order_ids_are_unique(self):
        broker = self._broker()
        ids = [broker.place_order("510300", "BUY", 4.0, 10)["broker_order_id"] for _ in range(5)]
        assert len(set(ids)) == 5


# ─────────────────────────────────────────────────────────────────────────────
# LiveGuard Phase 5 扩展
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveGuardExtended:
    def _guard(self, **kwargs):
        from execution.live_guard import LiveGuard
        return LiveGuard(**kwargs)

    # 原有接口向后兼容
    def test_original_interface_still_works(self):
        g = self._guard()
        ok, reason = g.can_place_live_order(True, 0, 5.0)
        assert ok and reason == "ok"

    def test_whitelist_allows_listed_symbol(self):
        g = self._guard(symbol_whitelist={"510300", "510500"})
        ok, reason = g.check_order("510300", 10_000)
        assert ok

    def test_whitelist_blocks_unlisted_symbol(self):
        g = self._guard(symbol_whitelist={"510300"})
        ok, reason = g.check_order("000001", 5_000)
        assert not ok
        assert reason == "symbol_not_in_whitelist"

    def test_empty_whitelist_allows_all(self):
        g = self._guard(symbol_whitelist=set())
        ok, _ = g.check_order("ANY", 100)
        assert ok

    def test_blacklist_blocks_symbol(self):
        g = self._guard(symbol_blacklist={"000001"})
        ok, reason = g.check_order("000001", 5_000)
        assert not ok
        assert reason == "symbol_in_blacklist"

    def test_single_notional_limit(self):
        g = self._guard(max_single_notional=100_000)
        ok, reason = g.check_order("510300", 200_000)
        assert not ok
        assert reason == "single_notional_limit"

    def test_single_notional_zero_means_unlimited(self):
        g = self._guard(max_single_notional=0)
        ok, _ = g.check_order("510300", 999_999_999)
        assert ok

    def test_daily_order_limit(self):
        g = self._guard(max_daily_orders=3)
        ok, reason = g.check_order("510300", 1_000, daily_order_count=3)
        assert not ok
        assert reason == "daily_order_limit"

    def test_daily_order_zero_means_unlimited(self):
        g = self._guard(max_daily_orders=0)
        ok, _ = g.check_order("510300", 1_000, daily_order_count=99999)
        assert ok

    def test_update_blacklist_from_graph(self):
        g = self._guard()
        g.update_blacklist_from_graph({"RISKY1", "RISKY2"})
        ok, reason = g.check_order("RISKY1", 1_000)
        assert not ok
        assert reason == "symbol_in_blacklist"

    def test_update_blacklist_appends(self):
        g = self._guard(symbol_blacklist={"A"})
        g.update_blacklist_from_graph({"B"})
        assert "A" in g.symbol_blacklist
        assert "B" in g.symbol_blacklist


# ─────────────────────────────────────────────────────────────────────────────
# Reconciler
# ─────────────────────────────────────────────────────────────────────────────

class TestReconciler:
    def _conn(self):
        """内存 SQLite 含 reconcile_reports 表。"""
        from data_store.schema import SCHEMA_STATEMENTS, apply_migrations
        conn = sqlite3.connect(":memory:")
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        apply_migrations(conn)
        conn.commit()
        return conn

    def _signals(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_clean_report_no_diff(self):
        from execution.reconciliation import Reconciler
        rec = Reconciler()
        signals = self._signals([
            {"symbol": "510300", "signal": 1, "position": 1.0},
        ])
        trades = [{"symbol": "510300", "side": "BUY", "qty": 100, "price": 4.5}]
        positions = {"510300": 100.0}
        report = rec.reconcile(signals, trades, positions, date="2024-01-15")
        assert report.is_clean is True
        assert report.date == "2024-01-15"

    def test_unmatched_trade_marks_dirty(self):
        from execution.reconciliation import Reconciler
        rec = Reconciler()
        signals = self._signals([{"symbol": "510300", "signal": 1, "position": 1.0}])
        # 成交了一个信号里没有的标的
        trades = [
            {"symbol": "510300", "side": "BUY", "qty": 100, "price": 4.5},
            {"symbol": "510500", "side": "BUY", "qty": 50, "price": 6.0},
        ]
        positions = {"510300": 100.0}
        report = rec.reconcile(signals, trades, positions, date="2024-01-15")
        assert report.is_clean is False
        assert any(t["symbol"] == "510500" for t in report.unmatched_trades)

    def test_position_drift_marks_dirty(self):
        from execution.reconciliation import Reconciler
        rec = Reconciler(position_tol=0.01)
        signals = self._signals([{"symbol": "510300", "signal": 1, "position": 1}])
        trades = [{"symbol": "510300", "side": "BUY", "qty": 100, "price": 4.5}]
        # 信号要求持仓（position=1），但实际持仓为 0 → 漂移
        positions = {}
        report = rec.reconcile(signals, trades, positions, date="2024-01-15")
        assert report.is_clean is False
        assert "510300" in report.position_drift

    def test_save_to_db_writes_row(self):
        from execution.reconciliation import Reconciler
        rec = Reconciler()
        conn = self._conn()
        signals = self._signals([{"symbol": "510300", "signal": 0, "position": 0.0}])
        report = rec.reconcile(signals, [], {}, date="2024-01-20")
        report_id = rec.save_to_db(conn, report)
        rows = conn.execute(
            "SELECT report_id, is_clean FROM reconcile_reports WHERE date='2024-01-20'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == report_id

    def test_save_to_db_idempotent(self):
        """两次 save 生成不同 report_id（UUID），两行都保留。"""
        from execution.reconciliation import Reconciler
        rec = Reconciler()
        conn = self._conn()
        signals = self._signals([{"signal": 0}])
        for _ in range(2):
            report = rec.reconcile(signals, [], {}, date="2024-01-21")
            rec.save_to_db(conn, report)
        rows = conn.execute(
            "SELECT COUNT(*) FROM reconcile_reports WHERE date='2024-01-21'"
        ).fetchone()
        assert rows[0] == 2  # 每次生成新 UUID，不会覆盖

    def test_dirty_report_saved_correctly(self):
        from execution.reconciliation import Reconciler
        rec = Reconciler()
        conn = self._conn()
        signals = self._signals([{"symbol": "510300", "signal": 1, "position": 1.0}])
        trades = [{"symbol": "GHOST", "side": "BUY", "qty": 1, "price": 1.0}]
        report = rec.reconcile(signals, trades, {}, date="2024-01-22")
        report_id = rec.save_to_db(conn, report)
        row = conn.execute(
            "SELECT is_clean FROM reconcile_reports WHERE report_id=?", (report_id,)
        ).fetchone()
        assert row[0] == 0  # is_clean=False → 0
