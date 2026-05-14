#!/usr/bin/env python3
"""
从新闻数据构建行业事件并计算行业分数（MVP）。
"""

from __future__ import annotations

import json
from pathlib import Path

from data.realtime_news import get_realtime_news
from research.events import build_events_from_news
from research.industry_scores import score_industries


def run(output_dir: str = "results/events") -> dict:
    news_df = get_realtime_news()
    rows = news_df.to_dict("records") if not news_df.empty else []
    events = build_events_from_news(rows)
    scores = score_industries(events)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "industry_scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"event_count": len(events), "industry_count": len(scores)}


if __name__ == "__main__":
    print(run())
