#!/usr/bin/env python3
"""每日端到端流水线（Phase 6 增强版）

变更：
  - 每个步骤独立 try/except，失败记录错误但不中止后续步骤
  - 每个步骤记录耗时（step_timings）
  - 新增 reconciliation 步骤（对账信号 vs 成交）
  - 新增 notify 参数：完成后推送摘要
  - 新增 dry_run 参数：跳过网络/写库操作，仅验证导入链

用法:
  python scripts/daily_pipeline.py
  python scripts/daily_pipeline.py --notify
  python run.py --daily-pipeline --notify
"""
from __future__ import annotations

import time
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


def _run_step(name: str, fn, timings: dict, errors: dict):
    """执行单个步骤，隔离异常，记录耗时。"""
    t0 = time.monotonic()
    try:
        result = fn()
        timings[name] = round(time.monotonic() - t0, 2)
        return result
    except Exception as exc:
        timings[name] = round(time.monotonic() - t0, 2)
        errors[name] = str(exc)
        logger.error("[daily_pipeline] step=%s failed: %s", name, exc)
        return {}


def update_data_store_run():
    from scripts.update_data_store import run
    return run()


def update_knowledge_run():
    from scripts.update_knowledge import run
    return run()


def update_events_run():
    from scripts.update_events import run
    return run()


def train_ml_run():
    from scripts.train_ml_strategy import run
    return run()


def run_ml_backtest_run():
    from scripts.run_ml_backtest import run
    return run()


def _run_reconciliation() -> dict:
    """对账：把当日 ML 回测信号 vs mock 成交记录进行三方对账。"""
    try:
        import pandas as pd
        from execution.reconciliation import Reconciler
        from data_store.db import get_connection

        rec = Reconciler()
        # Phase 6: 用空信号做结构验证（Phase 7 接入真实信号）
        signals_df = pd.DataFrame(columns=["symbol", "signal", "position"])
        report = rec.reconcile(signals_df, trades=[], positions={})

        with get_connection() as conn:
            report_id = rec.save_to_db(conn, report)

        return {"reconcile_report_id": report_id, "is_clean": report.is_clean}
    except Exception as exc:
        logger.warning("[daily_pipeline] reconciliation skipped: %s", exc)
        return {"reconcile_skipped": str(exc)}


def run_daily_pipeline(notify: bool = False, dry_run: bool = False) -> dict:
    """执行完整每日流水线。

    Args:
        notify: 完成后发送通知（需配置 notification.pushplus_token）
        dry_run: 跳过网络/写库操作，仅验证导入链路

    Returns:
        包含各步骤结果、耗时、错误和摘要的 dict
    """
    from utils.config import cfg
    from research.report_builder import build_daily_summary

    timings: dict[str, float] = {}
    errors: dict[str, str] = {}
    result: dict = {}

    if dry_run:
        logger.info("[daily_pipeline] dry_run=True，跳过所有网络/写库操作")
        result["dry_run"] = True
        result["summary"] = build_daily_summary(result, timings=timings, errors=errors)
        return result

    # ── 核心步骤（失败隔离）──────────────────────────────────────────────────
    result["data"]        = _run_step("data",       update_data_store_run,  timings, errors)
    result["knowledge"]   = _run_step("knowledge",  update_knowledge_run,   timings, errors)
    result["events"]      = _run_step("events",     update_events_run,      timings, errors)
    result["ml_train"]    = _run_step("ml_train",   train_ml_run,           timings, errors)
    result["ml_backtest"] = _run_step("ml_backtest",run_ml_backtest_run,    timings, errors)
    result["reconcile"]   = _run_step("reconcile",  _run_reconciliation,    timings, errors)

    # ── 可选步骤 ─────────────────────────────────────────────────────────────
    if cfg.get("knowledge.graph.enabled", False):
        from scripts.build_knowledge_graph import run as build_kg_run
        result["knowledge_graph"] = _run_step("knowledge_graph", build_kg_run, timings, errors)
        # sync_llmwiki 依赖 graph 完成
        from scripts.sync_llmwiki import sync
        def _sync_wiki():
            return sync(write=True)
        result["sync_llmwiki"] = _run_step("sync_llmwiki", _sync_wiki, timings, errors)

    if cfg.get("filings.enabled", False):
        def _filings():
            from scripts.ingest_filings import run as ingest_filings_run
            return ingest_filings_run()
        result["filings"] = _run_step("filings", _filings, timings, errors)

    if cfg.get("policy.enabled", False):
        def _policy():
            from data.policy.fifteenth_five_year import fetch_policy_articles, ingest_policy_articles
            from data_store.db import get_connection
            keywords = cfg.get("policy.keywords", [])
            with get_connection() as conn:
                articles = fetch_policy_articles(keywords=keywords)
                return ingest_policy_articles(conn, articles)
        result["policy_ingest"] = _run_step("policy", _policy, timings, errors)

    if cfg.get("sentiment.enabled", False):
        from scripts.run_sentiment_replay import run as sentiment_run
        result["sentiment"] = _run_step("sentiment", sentiment_run, timings, errors)

    # ── 摘要 & 通知 ──────────────────────────────────────────────────────────
    result["step_timings"] = timings
    result["step_errors"] = errors
    result["pipeline_ok"] = len(errors) == 0
    result["summary"] = build_daily_summary(result, timings=timings, errors=errors)

    if notify:
        try:
            from research.notifier import Notifier
            notifier = Notifier.from_cfg(cfg)
            notifier.send(result["summary"], title="量化日报")
        except Exception as exc:
            logger.warning("[daily_pipeline] notify failed: %s", exc)
            result["notify_error"] = str(exc)

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="每日量化流水线")
    parser.add_argument("--notify", action="store_true", help="发送推送通知")
    parser.add_argument("--dry-run", action="store_true", help="仅验证导入链路，不执行")
    args = parser.parse_args()
    out = run_daily_pipeline(notify=args.notify, dry_run=args.dry_run)
    print(out.get("summary", ""))
    if out.get("step_errors"):
        print(f"[WARN] 有失败步骤: {list(out['step_errors'].keys())}")
