from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KnowledgeDocument:
    source: str
    title: str
    url: str
    published_at: str
    content: str
    tags: list[str] = field(default_factory=list)
