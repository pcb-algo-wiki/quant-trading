#!/usr/bin/env python3
from __future__ import annotations

from research.report_builder import build_daily_summary


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


def run_daily_pipeline() -> dict:
    from utils.config import get_config

    cfg = get_config()
    result = {
        "data": update_data_store_run(),
        "knowledge": update_knowledge_run(),
        "events": update_events_run(),
        "ml_train": train_ml_run(),
        "ml_backtest": run_ml_backtest_run(),
    }
    if cfg.get("knowledge.graph.enabled", False):
        from scripts.build_knowledge_graph import run as build_kg_run
        result["knowledge_graph"] = build_kg_run()
    if cfg.get("filings.enabled", False):
        from scripts.ingest_filings import run as ingest_filings_run
        result["filings"] = ingest_filings_run()
    result["summary"] = build_daily_summary(result)
    return result


if __name__ == "__main__":
    print(run_daily_pipeline())
