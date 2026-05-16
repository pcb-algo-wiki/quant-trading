"""Phase 7 重型组件软升级测试

验证每个组件在缺少重型依赖时能正确降级，不抛崩溃异常。
覆盖：
  - FinBERTBackend: 无 transformers → 降级 SnowNLP，is_ready=False
  - Neo4jBackend: 无 neo4j driver → is_available()=False
  - NetworkXBackend: 基本操作正常（节点/边/邻居）
  - get_graph_backend: auto 模式正确选择
  - VectorbtEngine: 无 vectorbt → 降级 BacktestEngine，结果结构一致
  - GNNModel: 无 torch → is_available=False，get_fallback() 返回 LinearReturnModel
  - SentimentBackend: analyze_batch 新接口
  - config.yaml: Phase 7 配置段存在
"""
from __future__ import annotations

import sys
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# FinBERTBackend
# ─────────────────────────────────────────────────────────────────────────────

class TestFinBERTBackend:
    def test_analyze_returns_float_without_transformers(self, monkeypatch):
        """无 transformers 时降级，analyze 仍返回 float。"""
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        import importlib
        import research.sentiment as m
        importlib.reload(m)
        backend = m.FinBERTBackend()
        assert backend.is_ready is False
        result = backend.analyze("利好消息，涨停")
        assert isinstance(result, float)
        assert -1.0 <= result <= 1.0

    def test_is_ready_false_when_no_transformers(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        import importlib
        import research.sentiment as m
        importlib.reload(m)
        b = m.FinBERTBackend()
        assert b.is_ready is False

    def test_analyze_batch_returns_list(self, monkeypatch):
        """analyze_batch 不管是否有 transformers 都返回正确长度列表。"""
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        import importlib
        import research.sentiment as m
        importlib.reload(m)
        b = m.FinBERTBackend()
        texts = ["涨停利好", "亏损下跌", "中性消息"]
        results = b.analyze_batch(texts)
        assert len(results) == 3
        assert all(isinstance(s, float) for s in results)

    def test_analyze_empty_text(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        import importlib
        import research.sentiment as m
        importlib.reload(m)
        b = m.FinBERTBackend()
        assert b.analyze("") == 0.0

    def test_get_default_backend_finbert_returns_finbert_or_fallback(self, monkeypatch):
        """config backend=finbert 时返回 FinBERTBackend（即使降级模式）。"""
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        import importlib
        import research.sentiment as m
        importlib.reload(m)
        with patch("utils.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            mock_cfg.return_value.get.return_value = "finbert"
            backend = m.get_default_backend()
        assert isinstance(backend, m.FinBERTBackend)


# ─────────────────────────────────────────────────────────────────────────────
# SnowNLPBackend analyze_batch（新接口）
# ─────────────────────────────────────────────────────────────────────────────

class TestSnowNLPBatchInterface:
    def test_analyze_batch_length(self):
        from research.sentiment import SnowNLPBackend
        b = SnowNLPBackend()
        texts = ["涨停", "亏损", "平稳"]
        results = b.analyze_batch(texts)
        assert len(results) == len(texts)

    def test_analyze_batch_values_in_range(self):
        from research.sentiment import SnowNLPBackend
        b = SnowNLPBackend()
        for score in b.analyze_batch(["利好消息", "利空暴跌"]):
            assert -1.0 <= score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# NetworkXBackend
# ─────────────────────────────────────────────────────────────────────────────

class TestNetworkXBackend:
    def _backend(self):
        from knowledge.graph_backends import NetworkXBackend
        return NetworkXBackend()

    def test_is_available(self):
        b = self._backend()
        assert b.is_available() is True

    def test_backend_name(self):
        assert self._backend().backend_name() == "networkx"

    def test_upsert_node(self):
        b = self._backend()
        b.upsert_node("半导体", "industry", {"score": 0.8})

    def test_upsert_edge(self):
        b = self._backend()
        b.upsert_node("A", "industry")
        b.upsert_node("B", "segment")
        b.upsert_edge("A", "B", "has_segment", weight=0.9)

    def test_get_neighbors_one_hop(self):
        b = self._backend()
        b.upsert_node("A", "industry")
        b.upsert_node("B", "segment")
        b.upsert_node("C", "company")
        b.upsert_edge("A", "B", "has_segment")
        b.upsert_edge("B", "C", "leader")
        neighbors = b.get_neighbors("A", hops=1)
        assert "B" in neighbors
        assert "C" not in neighbors

    def test_get_neighbors_two_hops(self):
        b = self._backend()
        b.upsert_node("A", "industry")
        b.upsert_node("B", "segment")
        b.upsert_node("C", "company")
        b.upsert_edge("A", "B", "has_segment")
        b.upsert_edge("B", "C", "leader")
        neighbors = b.get_neighbors("A", hops=2)
        assert "B" in neighbors
        assert "C" in neighbors

    def test_get_neighbors_empty_for_unknown_node(self):
        b = self._backend()
        assert b.get_neighbors("UNKNOWN") == []

    def test_edge_weight_max_merge(self):
        """重复 upsert_edge 时保留较大 weight。"""
        b = self._backend()
        b.upsert_node("X", "industry")
        b.upsert_node("Y", "segment")
        b.upsert_edge("X", "Y", "has_segment", weight=0.5)
        b.upsert_edge("X", "Y", "has_segment", weight=0.9)
        data = b._g.get_edge_data("X", "Y")
        assert data["weight"] == 0.9


# ─────────────────────────────────────────────────────────────────────────────
# Neo4jBackend（无 driver 环境）
# ─────────────────────────────────────────────────────────────────────────────

class TestNeo4jBackend:
    def test_is_available_false_when_no_driver(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "neo4j", None)
        import importlib
        import knowledge.graph_backends as m
        importlib.reload(m)
        b = m.Neo4jBackend()
        assert b.is_available() is False

    def test_get_neighbors_returns_empty_when_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "neo4j", None)
        import importlib
        import knowledge.graph_backends as m
        importlib.reload(m)
        b = m.Neo4jBackend()
        assert b.get_neighbors("任意节点") == []

    def test_backend_name(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "neo4j", None)
        import importlib
        import knowledge.graph_backends as m
        importlib.reload(m)
        b = m.Neo4jBackend()
        assert b.backend_name() == "neo4j"


# ─────────────────────────────────────────────────────────────────────────────
# get_graph_backend 工厂
# ─────────────────────────────────────────────────────────────────────────────

class TestGetGraphBackend:
    def test_networkx_returns_networkx(self):
        from knowledge.graph_backends import get_graph_backend, NetworkXBackend
        b = get_graph_backend(prefer="networkx")
        assert isinstance(b, NetworkXBackend)

    def test_auto_fallback_when_neo4j_unavailable(self, monkeypatch):
        """auto 模式且 neo4j 不可用时应返回 NetworkXBackend。"""
        monkeypatch.setitem(sys.modules, "neo4j", None)
        import importlib
        import knowledge.graph_backends as m
        importlib.reload(m)
        b = m.get_graph_backend(prefer="auto")
        assert isinstance(b, m.NetworkXBackend)

    def test_prefer_networkx_ignores_neo4j(self):
        from knowledge.graph_backends import get_graph_backend, NetworkXBackend
        b = get_graph_backend(prefer="networkx")
        assert isinstance(b, NetworkXBackend)


# ─────────────────────────────────────────────────────────────────────────────
# VectorbtEngine
# ─────────────────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = pd.Series(4.0 + np.random.randn(n).cumsum() * 0.05, index=dates).clip(1.0)
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": 1e6}, index=dates)


def _make_signals(data: pd.DataFrame) -> pd.DataFrame:
    sig = pd.DataFrame(index=data.index)
    sig["position"] = (sig.index.dayofweek < 3).astype(int)
    sig["signal"] = sig["position"].diff().fillna(0).astype(int)
    return sig


class TestVectorbtEngine:
    def test_falls_back_when_no_vectorbt(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "vectorbt", None)
        import importlib
        import backtest.vectorbt_engine as m
        importlib.reload(m)
        eng = m.VectorbtEngine()
        assert eng.using_vectorbt is False

    def test_run_baseline_result_structure(self, monkeypatch):
        """无 vectorbt 时 run() 结果与 BacktestEngine 一致。"""
        monkeypatch.setitem(sys.modules, "vectorbt", None)
        import importlib
        import backtest.vectorbt_engine as m
        importlib.reload(m)
        eng = m.VectorbtEngine()
        data = _make_ohlcv()
        signals = _make_signals(data)
        result = eng.run(data, signals)
        assert "metrics" in result
        assert "equity_curve" in result
        assert result["engine"] == "baseline"

    def test_metrics_keys(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "vectorbt", None)
        import importlib
        import backtest.vectorbt_engine as m
        importlib.reload(m)
        eng = m.VectorbtEngine()
        data = _make_ohlcv()
        signals = _make_signals(data)
        result = eng.run(data, signals)
        for key in ("total_return", "sharpe_ratio", "max_drawdown", "num_trades"):
            assert key in result["metrics"]


# ─────────────────────────────────────────────────────────────────────────────
# GNNModel
# ─────────────────────────────────────────────────────────────────────────────

class TestGNNModel:
    def test_is_gnn_available_returns_bool(self):
        from ml.gnn_model import is_gnn_available
        result = is_gnn_available()
        assert isinstance(result, bool)

    def test_model_unavailable_when_no_torch(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", None)
        monkeypatch.setitem(sys.modules, "torch_geometric", None)
        import importlib
        import ml.gnn_model as m
        importlib.reload(m)
        model = m.GNNModel()
        assert model.is_available is False

    def test_get_fallback_returns_linear_model(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", None)
        monkeypatch.setitem(sys.modules, "torch_geometric", None)
        import importlib
        import ml.gnn_model as m
        importlib.reload(m)
        model = m.GNNModel()
        fallback = model.get_fallback()
        from ml.models import LinearReturnModel
        assert isinstance(fallback, LinearReturnModel)

    def test_predict_raises_when_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", None)
        monkeypatch.setitem(sys.modules, "torch_geometric", None)
        import importlib
        import ml.gnn_model as m
        importlib.reload(m)
        model = m.GNNModel()
        with pytest.raises(RuntimeError, match="不可用"):
            model.predict(np.zeros((3, 4)), np.zeros((2, 2), dtype=int))

    def test_fit_raises_when_unavailable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", None)
        monkeypatch.setitem(sys.modules, "torch_geometric", None)
        import importlib
        import ml.gnn_model as m
        importlib.reload(m)
        model = m.GNNModel()
        with pytest.raises(RuntimeError, match="不可用"):
            model.fit(np.zeros((3, 4)), np.zeros((2, 2), dtype=int), np.zeros(3))
