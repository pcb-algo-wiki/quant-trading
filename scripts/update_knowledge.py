#!/usr/bin/env python3
"""
根据新闻文档更新行业知识卡片（MVP）。
"""

from __future__ import annotations

import sys, json
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.realtime_news import get_realtime_news
from knowledge.sources import from_news_rows
from knowledge.updater import update_industry_cards
from knowledge.taxonomy import list_seed_industries


def run(output_path: str = "results/knowledge/cards.json") -> dict[str, dict]:
    news_df = get_realtime_news()
    rows = news_df.to_dict("records") if not news_df.empty else []

    # MVP 默认标记为 AI 算力主题，后续由事件分类器替换
    docs = from_news_rows(rows, default_tag="ai_compute")
    cards = update_industry_cards(docs)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
    return cards


if __name__ == "__main__":
    result = run()
    print(f"updated industries: {sorted(result.keys())}")
    print(f"seed industries: {list_seed_industries()}")
