#!/usr/bin/env python3
"""历史新闻情感重放脚本

流程：
1. 从 data_store 加载 IndustryGraph
2. 构建 PolicyAligner（从 policy_items）
3. 读取 news_items（可按 start_date 过滤）
4. 对每条新闻：情感打分 → 政策对齐 → 传播 → 写 industry_events
5. 打印汇总
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from data_store.db import get_connection
from knowledge.graph import IndustryGraph
from research.sentiment import get_default_backend
from research.policy_alignment import build_aligner_from_store
from research.propagation import propagate_scores, build_industry_events, upsert_event_scores


def run(start_date: str | None = None, dry_run: bool = False) -> dict:
    """执行情感重放。

    Args:
        start_date: ISO 日期字符串（含），默认最近 30 天
        dry_run: True 时只打印不写库

    Returns:
        {"processed": int, "inserted": int, "errors": int}
    """
    from utils.config import get_config

    cfg = get_config()
    decay = cfg.get("sentiment.decay", 0.5)
    max_hops = cfg.get("sentiment.max_hops", 2)

    if start_date is None:
        start_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    processed = inserted = errors = 0

    with get_connection() as conn:
        graph = IndustryGraph()
        graph.load_from_store(conn)

        aligner = build_aligner_from_store(conn)
        backend = get_default_backend()

        rows = conn.execute(
            "SELECT * FROM news_items WHERE published_at >= ? ORDER BY published_at",
            (start_date,),
        ).fetchall()

        for row in rows:
            try:
                row_dict = dict(row)
                text = f"{row_dict.get('title', '')} {row_dict.get('content', '') or ''}"
                sentiment_score = backend.analyze(text)
                policy_score = aligner.score(text)

                seed_node = row_dict.get("related_symbol") or row_dict.get("industry")
                if seed_node and not graph.has_node(seed_node):
                    seed_node = None

                if seed_node:
                    propagated = propagate_scores(
                        graph,
                        {seed_node: sentiment_score},
                        decay=decay,
                        max_hops=max_hops,
                    )
                else:
                    propagated = {}

                events = build_industry_events(row_dict, sentiment_score, policy_score, propagated)

                if not dry_run and events:
                    upsert_event_scores(conn, events)
                    inserted += len(events)

                processed += 1
            except Exception as e:
                print(f"[replay] 处理失败: {e}", file=sys.stderr)
                errors += 1

    summary = {"processed": processed, "inserted": inserted, "errors": errors}
    print(f"[replay] 完成: {summary}")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="情感重放脚本")
    parser.add_argument("--start-date", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = parser.parse_args()
    run(start_date=args.start_date, dry_run=args.dry_run)
