#!/usr/bin/env python3
"""
scripts/build_knowledge_graph.py
================================
Phase 1：从 ``data_store`` 中的 news_items / policy_items / financial_reports
增量构建 ``IndustryGraph``，并把证据回链写入 ``knowledge_evidence``。

幂等性：
- 节点 / 边走 ``IndustryGraph.save_to_store`` 的 UPSERT 语义。
- 证据走 ``KnowledgeEvidenceRepository.upsert`` 的复合主键 UPSERT。

调用：
    python scripts/build_knowledge_graph.py
    或在代码里 ``from scripts.build_knowledge_graph import run; run()``
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from data_store.db import get_connection
from data_store.knowledge_repo import KnowledgeEvidenceRepository
from knowledge.extractors import EntityExtractor, ExtractionResult, RuleEntityExtractor
from knowledge.graph import IndustryGraph
from knowledge.taxonomy import DEFAULT_TAXONOMY


def _doc_node_id(source: str, content_hash: str) -> str:
    return f"doc:{source}:{content_hash[:16]}"


def _snippet(text: str, limit: int = 200) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:limit]


def _iter_news(conn: sqlite3.Connection) -> Iterable[dict]:
    cur = conn.execute(
        "SELECT source, title, content, content_hash, published_at FROM news_items"
    )
    for row in cur:
        yield {
            "source": row["source"],
            "title": row["title"] or "",
            "content": row["content"] or "",
            "content_hash": row["content_hash"],
            "published_at": row["published_at"],
            "kind": "news",
        }


def _iter_policy(conn: sqlite3.Connection) -> Iterable[dict]:
    cur = conn.execute(
        "SELECT source, title, content, content_hash, published_at FROM policy_items"
    )
    for row in cur:
        yield {
            "source": row["source"],
            "title": row["title"] or "",
            "content": row["content"] or "",
            "content_hash": row["content_hash"],
            "published_at": row["published_at"],
            "kind": "policy",
        }


def _iter_filings(conn: sqlite3.Connection) -> Iterable[dict]:
    cur = conn.execute(
        "SELECT symbol, report_period, source FROM financial_reports"
    )
    for row in cur:
        text = f"{row['symbol']} {row['report_period']} 财报"
        yield {
            "source": row["source"],
            "title": text,
            "content": text,
            "content_hash": f"{row['symbol']}-{row['report_period']}",
            "published_at": row["report_period"],
            "kind": "filing",
            "symbol": row["symbol"],
        }


def _process_doc(
    graph: IndustryGraph,
    ev_repo: KnowledgeEvidenceRepository,
    extractor: EntityExtractor,
    doc: dict,
) -> tuple[int, int]:
    """处理单条文档，返回 (新增节点数估计, 新增边数估计)。"""
    doc_node = _doc_node_id(doc["source"], doc["content_hash"])
    title = doc["title"]
    content = doc["content"]
    text = f"{title}\n{content}"
    graph.upsert_node(
        doc_node,
        "document",
        title or doc_node,
        kind=doc.get("kind", "news"),
        published_at=doc.get("published_at"),
        source=doc["source"],
    )

    result: ExtractionResult = extractor.extract(text)

    edges = 0
    nodes = 1

    # 财报特例：直接把 symbol 作为公司节点
    if doc.get("kind") == "filing" and doc.get("symbol"):
        sym = doc["symbol"]
        if sym not in result.companies:
            result.companies.append(sym)

    for sym in result.companies:
        if not graph.has_node(sym):
            graph.upsert_node(sym, "company", sym)
            nodes += 1
        graph.upsert_edge(sym, doc_node, "mentioned_in", weight=0.5)
        ev_repo.upsert(sym, doc["source"], doc["content_hash"], snippet=_snippet(text))
        edges += 1

    for seg in result.segments:
        if not graph.has_node(seg):
            industry, layer, name = seg.split(":", 2)
            graph.upsert_node(seg, "segment", name, layer=layer)
            nodes += 1
        graph.upsert_edge(seg, doc_node, "mentioned_in", weight=0.3)
        ev_repo.upsert(seg, doc["source"], doc["content_hash"], snippet=_snippet(text))
        edges += 1

    for ind in result.industries:
        if not graph.has_node(ind):
            graph.upsert_node(ind, "industry", ind)
            nodes += 1
        graph.upsert_edge(ind, doc_node, "mentioned_in", weight=0.4)
        ev_repo.upsert(ind, doc["source"], doc["content_hash"], snippet=_snippet(text))
        edges += 1

    if doc.get("kind") == "policy" and (result.companies or result.industries):
        policy_node = f"policy:{doc['source']}:{doc['content_hash'][:16]}"
        graph.upsert_node(policy_node, "policy", title or policy_node)
        nodes += 1
        for sym in result.companies:
            graph.upsert_edge(sym, policy_node, "affected_by", weight=0.5)
            edges += 1
        for ind in result.industries:
            graph.upsert_edge(ind, policy_node, "affected_by", weight=0.5)
            edges += 1

    return nodes, edges


def run(
    db_path: str | None = None,
    company_dict: dict[str, str] | None = None,
) -> dict:
    """从 data_store 增量构建知识图谱，返回统计。"""
    extractor = RuleEntityExtractor(
        company_dict=company_dict or {},
        taxonomy=DEFAULT_TAXONOMY,
    )

    stats = {"docs": 0, "nodes_touched": 0, "edges_touched": 0}

    with get_connection(db_path) as conn:
        try:
            graph = IndustryGraph.load_from_store(conn)
        except sqlite3.OperationalError:
            graph = IndustryGraph()

        # 注入 taxonomy 基线节点（幂等）
        graph.add_taxonomy(DEFAULT_TAXONOMY)

        ev_repo = KnowledgeEvidenceRepository(conn)

        for source_iter in (_iter_news(conn), _iter_policy(conn), _iter_filings(conn)):
            for doc in source_iter:
                n, e = _process_doc(graph, ev_repo, extractor, doc)
                stats["docs"] += 1
                stats["nodes_touched"] += n
                stats["edges_touched"] += e

        n_total, e_total = graph.save_to_store(conn)
        stats["nodes_in_store"] = n_total
        stats["edges_in_store"] = e_total
        conn.commit()

    return stats


if __name__ == "__main__":
    result = run()
    print(result)
