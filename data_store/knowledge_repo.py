"""
data_store.knowledge_repo
=========================
Phase 1 — knowledge_evidence 表的写入辅助。
节点 / 边的持久化由 ``knowledge.graph.IndustryGraph.save_to_store`` 负责。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


class KnowledgeEvidenceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(
        self,
        node_id: str,
        doc_source: str,
        doc_hash: str,
        snippet: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO knowledge_evidence (node_id, doc_source, doc_hash, snippet, ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(node_id, doc_source, doc_hash) DO UPDATE SET
                snippet=excluded.snippet,
                ts=excluded.ts
            """,
            (node_id, doc_source, doc_hash, snippet, _now()),
        )
        return cur.rowcount

    def for_node(self, node_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT doc_source, doc_hash, snippet, ts FROM knowledge_evidence WHERE node_id=?",
            (node_id,),
        )
        return [dict(row) for row in cur.fetchall()]
