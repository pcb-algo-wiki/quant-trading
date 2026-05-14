from __future__ import annotations

from datetime import datetime

from knowledge.models import KnowledgeDocument


def build_industry_card(industry: str, documents: list[KnowledgeDocument]) -> dict:
    sources = [
        {
            "source": d.source,
            "title": d.title,
            "url": d.url,
            "published_at": d.published_at,
        }
        for d in documents
    ]

    highlights = [d.title for d in documents[:5]]
    return {
        "industry": industry,
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "doc_count": len(documents),
        "highlights": highlights,
        "sources": sources,
    }
