#!/usr/bin/env python3
"""
同步行情与新闻到结构化数据存储。
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta

from data.fetcher import fetch_etf
from data.realtime_news import get_realtime_news
from data_store.db import get_connection
from data_store.repositories import MarketBarRepository, NewsRepository, PipelineRunRepository
from utils.config import cfg


def run(days: int = 30, db_path: str | None = None) -> dict:
    summary = {"bars_inserted": 0, "news_inserted": 0}
    end = datetime.now()
    start = (end - timedelta(days=days)).strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")

    with get_connection(db_path) as conn:
        pipeline_repo = PipelineRunRepository(conn)
        run_id = pipeline_repo.start("update_data_store")
        try:
            market_repo = MarketBarRepository(conn)
            news_repo = NewsRepository(conn)

            for code in cfg.enabled_etf_codes:
                bars = fetch_etf(code, start=start, end=end_s)
                summary["bars_inserted"] += market_repo.upsert_dataframe(symbol=code, source="sina", bars=bars)

            news_df = get_realtime_news()
            summary["news_inserted"] += news_repo.upsert_dataframe(source="aggregated", news=news_df)

            pipeline_repo.finish(run_id=run_id, status="success")
        except Exception as e:
            pipeline_repo.finish(run_id=run_id, status="failed", error=str(e))
            raise

    return summary


if __name__ == "__main__":
    result = run()
    print(result)
