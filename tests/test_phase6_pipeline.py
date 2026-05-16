"""Phase 6 端到端流水线与可观测性测试

覆盖：
  - daily_pipeline: 步骤失败隔离，dry_run，结果结构
  - report_builder: build_daily_summary 输出格式
  - Notifier: 条件告警，dry_run 发送，无 token 静默
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# report_builder
# ─────────────────────────────────────────────────────────────────────────────

class TestReportBuilder:
    def _summary(self, **kwargs):
        from research.report_builder import build_daily_summary
        return build_daily_summary(kwargs)

    def test_summary_contains_date(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({})
        assert "量化日报" in out

    def test_summary_data_bars(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({"data": {"bars_inserted": 42, "news_inserted": 7}})
        assert "42" in out
        assert "7" in out

    def test_summary_ml_fields(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({
            "ml_train": {"n_windows": 5, "avg_mse": 0.0123},
            "ml_backtest": {"total_return": 0.18},
        })
        assert "5" in out
        assert "18.00%" in out

    def test_summary_events(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({"events": {"event_count": 99, "industry_count": 12}})
        assert "99" in out
        assert "12" in out

    def test_summary_timings_included(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({}, timings={"data": 1.23, "ml_train": 5.67})
        assert "1.23" in out
        assert "5.67" in out

    def test_summary_errors_included(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({}, errors={"ml_train": "timeout"})
        assert "ml_train" in out
        assert "timeout" in out

    def test_summary_ok_icon(self):
        from research.report_builder import build_daily_summary
        ok = build_daily_summary({"pipeline_ok": True})
        fail = build_daily_summary({"pipeline_ok": False})
        assert "✅" in ok
        assert "⚠️" in fail

    def test_summary_reconcile_clean(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({"reconcile": {"is_clean": True, "reconcile_report_id": "rec-123"}})
        assert "rec-123" in out
        assert "干净" in out

    def test_summary_reconcile_dirty(self):
        from research.report_builder import build_daily_summary
        out = build_daily_summary({"reconcile": {"is_clean": False}})
        assert "差异" in out


# ─────────────────────────────────────────────────────────────────────────────
# Notifier
# ─────────────────────────────────────────────────────────────────────────────

class TestNotifier:
    def test_send_without_token_returns_true(self):
        from research.notifier import Notifier
        n = Notifier(pushplus_token="")
        assert n.send("hello") is True

    def test_send_dry_run_returns_true(self):
        from research.notifier import Notifier
        n = Notifier(pushplus_token="fake-token", dry_run=True)
        assert n.send("hello") is True

    def test_send_placeholder_token_returns_true(self):
        from research.notifier import Notifier
        n = Notifier(pushplus_token="${PUSHPLUS_TOKEN}")
        assert n.send("hello") is True

    def test_from_cfg_extracts_token(self):
        from research.notifier import Notifier
        mock_cfg = MagicMock()
        mock_cfg.get.return_value = {
            "pushplus_token": "abc123",
            "dingtalk_webhook": "",
        }
        n = Notifier.from_cfg(mock_cfg)
        assert n.pushplus_token == "abc123"

    def test_should_alert_pipeline_failure(self):
        from research.notifier import Notifier
        n = Notifier()
        payload = {
            "pipeline_ok": False,
            "step_errors": {"ml_train": "timeout"},
        }
        reasons = n.should_alert(payload)
        assert any("流水线步骤失败" in r for r in reasons)

    def test_should_alert_drawdown(self):
        from research.notifier import Notifier
        n = Notifier()
        payload = {
            "pipeline_ok": True,
            "ml_backtest": {"max_drawdown": -0.20},
        }
        reasons = n.should_alert(payload)
        assert any("回撤" in r for r in reasons)

    def test_should_alert_no_data(self):
        from research.notifier import Notifier
        n = Notifier()
        payload = {"pipeline_ok": True, "data": {"bars_inserted": 0}}
        reasons = n.should_alert(payload)
        assert any("数据缺失" in r for r in reasons)

    def test_should_alert_clean_returns_empty(self):
        from research.notifier import Notifier
        n = Notifier()
        payload = {
            "pipeline_ok": True,
            "data": {"bars_inserted": 10},
            "ml_backtest": {"max_drawdown": -0.05},
        }
        assert n.should_alert(payload) == []


# ─────────────────────────────────────────────────────────────────────────────
# daily_pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyPipeline:
    """mock 各步骤，验证 pipeline 框架逻辑。"""

    def _mock_step(self, result: dict | None = None, raise_exc: Exception | None = None):
        """返回一个 mock 函数：成功返回 result，失败抛出 raise_exc。"""
        def fn():
            if raise_exc:
                raise raise_exc
            return result or {}
        return fn

    def test_dry_run_skips_steps(self):
        from scripts.daily_pipeline import run_daily_pipeline
        out = run_daily_pipeline(dry_run=True)
        assert out.get("dry_run") is True
        assert "summary" in out
        # 没有 step_timings（dry run 直接返回）
        assert "step_errors" not in out

    def test_result_contains_summary(self):
        """mock 所有步骤成功，验证结果含 summary。"""
        with patch("scripts.daily_pipeline.update_data_store_run", return_value={"bars_inserted": 5}), \
             patch("scripts.daily_pipeline.update_knowledge_run", return_value={}), \
             patch("scripts.daily_pipeline.update_events_run", return_value={"event_count": 3}), \
             patch("scripts.daily_pipeline.train_ml_run", return_value={"n_windows": 2, "avg_mse": 0.01}), \
             patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={"total_return": 0.1}), \
             patch("scripts.daily_pipeline._run_reconciliation", return_value={"is_clean": True}):
            from scripts.daily_pipeline import run_daily_pipeline
            out = run_daily_pipeline()
        assert "summary" in out
        assert "量化日报" in out["summary"]

    def test_step_failure_isolated(self):
        """一个步骤失败时，其余步骤仍然执行。"""
        with patch("scripts.daily_pipeline.update_data_store_run", side_effect=RuntimeError("网络超时")), \
             patch("scripts.daily_pipeline.update_knowledge_run", return_value={}), \
             patch("scripts.daily_pipeline.update_events_run", return_value={}), \
             patch("scripts.daily_pipeline.train_ml_run", return_value={}), \
             patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={}), \
             patch("scripts.daily_pipeline._run_reconciliation", return_value={}):
            from scripts.daily_pipeline import run_daily_pipeline
            out = run_daily_pipeline()
        assert "data" in out.get("step_errors", {})
        assert out["pipeline_ok"] is False

    def test_timings_recorded(self):
        """验证每个步骤都记录了耗时。"""
        with patch("scripts.daily_pipeline.update_data_store_run", return_value={}), \
             patch("scripts.daily_pipeline.update_knowledge_run", return_value={}), \
             patch("scripts.daily_pipeline.update_events_run", return_value={}), \
             patch("scripts.daily_pipeline.train_ml_run", return_value={}), \
             patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={}), \
             patch("scripts.daily_pipeline._run_reconciliation", return_value={}):
            from scripts.daily_pipeline import run_daily_pipeline
            out = run_daily_pipeline()
        assert "step_timings" in out
        timings = out["step_timings"]
        for step in ("data", "knowledge", "events", "ml_train", "ml_backtest"):
            assert step in timings
            assert isinstance(timings[step], float)

    def test_pipeline_ok_true_when_all_succeed(self):
        with patch("scripts.daily_pipeline.update_data_store_run", return_value={}), \
             patch("scripts.daily_pipeline.update_knowledge_run", return_value={}), \
             patch("scripts.daily_pipeline.update_events_run", return_value={}), \
             patch("scripts.daily_pipeline.train_ml_run", return_value={}), \
             patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={}), \
             patch("scripts.daily_pipeline._run_reconciliation", return_value={}):
            from scripts.daily_pipeline import run_daily_pipeline
            out = run_daily_pipeline()
        assert out["pipeline_ok"] is True

    def test_notify_called_when_flag_true(self):
        """--notify 时调用 Notifier.send。"""
        with patch("scripts.daily_pipeline.update_data_store_run", return_value={}), \
             patch("scripts.daily_pipeline.update_knowledge_run", return_value={}), \
             patch("scripts.daily_pipeline.update_events_run", return_value={}), \
             patch("scripts.daily_pipeline.train_ml_run", return_value={}), \
             patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={}), \
             patch("scripts.daily_pipeline._run_reconciliation", return_value={}), \
             patch("research.notifier.Notifier.from_cfg") as mock_from_cfg:
            mock_notifier = MagicMock()
            mock_from_cfg.return_value = mock_notifier
            from scripts.daily_pipeline import run_daily_pipeline
            run_daily_pipeline(notify=True)
        mock_notifier.send.assert_called_once()

    def test_multiple_steps_fail_all_recorded(self):
        """多步骤失败时，所有失败都记录在 step_errors 中。"""
        with patch("scripts.daily_pipeline.update_data_store_run", side_effect=RuntimeError("err1")), \
             patch("scripts.daily_pipeline.update_knowledge_run", side_effect=ValueError("err2")), \
             patch("scripts.daily_pipeline.update_events_run", return_value={}), \
             patch("scripts.daily_pipeline.train_ml_run", return_value={}), \
             patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={}), \
             patch("scripts.daily_pipeline._run_reconciliation", return_value={}):
            from scripts.daily_pipeline import run_daily_pipeline
            out = run_daily_pipeline()
        assert "data" in out["step_errors"]
        assert "knowledge" in out["step_errors"]
        # events 步骤依然执行
        assert "events" not in out["step_errors"]
