"""Phase 17.2/17.4/17.5 — 指标记录 / 配置历史 / 审计 trace 测试"""
from __future__ import annotations

import pytest

from data_store.db import get_connection
from data_store.metrics_recorder import MetricsRecorder
from data_store.config_history import ConfigHistory
from data_store.audit_trace import AuditTrace


# ============ 17.2 metrics_daily ============

def test_metrics_recorder_record_and_query(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        rec = MetricsRecorder(conn)
        rec.record("2024-01-15", "data_health_score", 0.95)
        rec.record("2024-01-15", "pipeline_success_rate", 1.0)
        rec.record("2024-01-16", "data_health_score", 0.92)

        rows = rec.query_range("data_health_score", "2024-01-15", "2024-01-16")
        assert len(rows) == 2
        values = [r["value"] for r in rows]
        assert 0.95 in values and 0.92 in values


def test_metrics_recorder_upsert_same_day(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        rec = MetricsRecorder(conn)
        rec.record("2024-01-15", "ic_score", 0.05)
        rec.record("2024-01-15", "ic_score", 0.08)  # 覆盖
        rows = rec.query_range("ic_score", "2024-01-15", "2024-01-15")
        assert len(rows) == 1
        assert rows[0]["value"] == 0.08


# ============ 17.4 config history ============

def test_config_history_snapshot_and_retrieve(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        hist = ConfigHistory(conn)
        yaml = "strategy:\n  name: ma_cross\n"
        snapshot_id = hist.snapshot(yaml, note="初始版本")
        assert isinstance(snapshot_id, int)
        latest = hist.get_latest()
        assert latest["yaml_content"] == yaml
        assert latest["note"] == "初始版本"


def test_config_history_dedup_identical_content(tmp_path):
    """相同内容不应重复入库。"""
    with get_connection(str(tmp_path / "q.db")) as conn:
        hist = ConfigHistory(conn)
        yaml = "a: 1\n"
        id1 = hist.snapshot(yaml)
        id2 = hist.snapshot(yaml)
        assert id1 == id2


# ============ 17.5 audit trace ============

def test_audit_trace_full_signal_to_fill_chain(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        audit = AuditTrace(conn)
        trace_id = audit.new_trace_id()
        audit.log(trace_id, "signal", {"symbol": "600519", "side": "buy"})
        audit.log(trace_id, "order", {"order_id": "O1", "qty": 100})
        audit.log(trace_id, "fill", {"order_id": "O1", "price": 1800.0})
        events = audit.get_chain(trace_id)
        assert len(events) == 3
        assert [e["stage"] for e in events] == ["signal", "order", "fill"]


def test_audit_trace_query_by_trace_id_returns_chronological(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        audit = AuditTrace(conn)
        tid = audit.new_trace_id()
        audit.log(tid, "signal", {"x": 1})
        audit.log(tid, "order", {"x": 2})
        chain = audit.get_chain(tid)
        assert chain[0]["stage"] == "signal"
        assert chain[1]["stage"] == "order"
