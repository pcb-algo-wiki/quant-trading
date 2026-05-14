from __future__ import annotations

from knowledge.models import KnowledgeDocument


def from_news_rows(rows: list[dict], default_tag: str | None = None) -> list[KnowledgeDocument]:
    docs: list[KnowledgeDocument] = []
    for row in rows:
        tags = list(row.get("tags", []))
        if default_tag and default_tag not in tags:
            tags.append(default_tag)
        docs.append(
            KnowledgeDocument(
                source=str(row.get("source", "unknown")),
                title=str(row.get("title", "")),
                url=str(row.get("url", "")),
                published_at=str(row.get("published_at", row.get("time", ""))),
                content=str(row.get("content", "")),
                tags=tags,
            )
        )
    return docs
