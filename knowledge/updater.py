from __future__ import annotations

from collections import defaultdict

from knowledge.cards import build_industry_card
from knowledge.models import KnowledgeDocument


def update_industry_cards(documents: list[KnowledgeDocument]) -> dict[str, dict]:
    grouped: dict[str, list[KnowledgeDocument]] = defaultdict(list)
    for doc in documents:
        for tag in doc.tags:
            grouped[tag].append(doc)

    cards = {}
    for industry, docs in grouped.items():
        cards[industry] = build_industry_card(industry=industry, documents=docs)
    return cards
