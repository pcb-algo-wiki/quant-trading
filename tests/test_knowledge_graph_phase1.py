"""Phase 1 Hybrid GraphRAG MVP tests."""
from __future__ import annotations

import pandas as pd

from data_store.db import get_connection
from data_store.knowledge_repo import KnowledgeEvidenceRepository
from data_store.repositories import NewsRepository
from knowledge.extractors import RuleEntityExtractor
from knowledge.graph import IndustryGraph, build_industry_graph
from knowledge.retrieval import (
    BM25Retriever,
    Document,
    GraphNeighborRetriever,
    HybridRetriever,
    rrf_fuse,
    tokenize,
)
from knowledge.taxonomy import DEFAULT_TAXONOMY
from scripts.build_knowledge_graph import run as build_kg_run


# --- 1. 向后兼容 ---


def test_build_industry_graph_backcompat_shape():
    taxonomy = {
        "ai_compute": {
            "name": "AI算力",
            "upstream": ["chips"],
            "midstream": ["servers"],
            "downstream": ["training"],
        }
    }
    leaders = [{"industry": "ai_compute", "symbol": "688256", "name": "寒武纪"}]
    out = build_industry_graph(taxonomy=taxonomy, leaders=leaders)

    assert "ai_compute" in out["nodes"]
    assert "688256" in out["nodes"]
    assert any(
        e["source"] == "ai_compute" and e["target"] == "688256" and e["type"] == "leader"
        for e in out["edges"]
    )


# --- 2. IndustryGraph 基础语义 ---


def test_industry_graph_upsert_is_idempotent():
    g = IndustryGraph()
    g.upsert_node("688256", "company", "寒武纪")
    g.upsert_node("688256", "company", "寒武纪", market="A")
    assert g.node_count() == 1
    assert g.get_node("688256")["attrs"]["market"] == "A"


def test_industry_graph_neighbors_bfs():
    g = IndustryGraph()
    g.add_taxonomy(DEFAULT_TAXONOMY)
    g.add_leader("ai_compute", "688256", "寒武纪")
    neighbors_1 = g.neighbors("ai_compute", hops=1)
    assert "688256" in neighbors_1
    # 2 跳能从 company 找回行业下的 segment
    neighbors_2 = g.neighbors("688256", hops=2)
    assert any(n.startswith("ai_compute:") for n in neighbors_2)


def test_industry_graph_round_trip_persistence(tmp_path):
    db = tmp_path / "kg.db"
    with get_connection(str(db)) as conn:
        g = IndustryGraph()
        g.add_taxonomy({"x": {"name": "X", "upstream": ["a"], "midstream": [], "downstream": []}})
        g.add_leader("x", "000001", "平安")
        n, e = g.save_to_store(conn)
        assert n >= 3 and e >= 2

    with get_connection(str(db)) as conn:
        g2 = IndustryGraph.load_from_store(conn)
        assert g2.has_node("x")
        assert g2.has_node("000001")
        # 二次保存仍应幂等
        n2, e2 = g2.save_to_store(conn)
        assert n2 == g2.node_count()
        # 节点数不应变化
        g3 = IndustryGraph.load_from_store(conn)
        assert g3.node_count() == g2.node_count()


# --- 3. 抽取器 ---


def test_rule_extractor_finds_company_and_segment():
    extractor = RuleEntityExtractor(
        company_dict={"688256": "寒武纪"},
        taxonomy=DEFAULT_TAXONOMY,
    )
    text = "寒武纪 688256 发布新一代 chips, 进军 data_center 市场, 受十四五规划利好"
    r = extractor.extract(text)
    assert "688256" in r.companies
    assert any(s.endswith(":chips") for s in r.segments)
    assert any("data_center" in s for s in r.segments)
    assert "ai_compute" in r.industries or "semiconductor" in r.industries
    assert "five_year_plan" in r.policy_tags


def test_rule_extractor_negative_sample_no_false_positive():
    extractor = RuleEntityExtractor(company_dict={"688256": "寒武纪"})
    r = extractor.extract("今天天气很好，适合户外活动")
    assert r.companies == []
    assert r.policy_tags == []


# --- 4. Retrieval ---


def test_bm25_basic_ranking():
    docs = [
        Document(doc_id="d1", text="GPU 算力 训练 模型"),
        Document(doc_id="d2", text="债券 国债 收益率"),
        Document(doc_id="d3", text="GPU 模型 推理"),
    ]
    bm25 = BM25Retriever(docs)
    hits = bm25.search("GPU 训练", top_k=2)
    assert hits and hits[0].doc_id == "d1"
    assert all(h.evidence_chain for h in hits)


def test_rrf_fuse_combines_rankings():
    r1 = [
        type("H", (), {"doc_id": "a", "score": 0.9, "source": "bm25", "evidence_chain": ["bm25:a"], "extra": {}})(),
        type("H", (), {"doc_id": "b", "score": 0.5, "source": "bm25", "evidence_chain": ["bm25:b"], "extra": {}})(),
    ]
    r2 = [
        type("H", (), {"doc_id": "b", "score": 0.8, "source": "graph", "evidence_chain": ["graph:b"], "extra": {}})(),
        type("H", (), {"doc_id": "c", "score": 0.4, "source": "graph", "evidence_chain": ["graph:c"], "extra": {}})(),
    ]
    fused = rrf_fuse([r1, r2], k=10)
    ids = [h.doc_id for h in fused]
    # b 同时出现在两路，应排第一
    assert ids[0] == "b"
    b_hit = next(h for h in fused if h.doc_id == "b")
    assert any("bm25" in ev for ev in b_hit.evidence_chain)
    assert any("graph" in ev for ev in b_hit.evidence_chain)


def test_hybrid_retriever_returns_evidence_chain():
    docs = [Document(doc_id="d1", text="GPU 训练 模型 寒武纪")]
    bm25 = BM25Retriever(docs)
    g = IndustryGraph()
    g.add_taxonomy(DEFAULT_TAXONOMY)
    g.upsert_node("688256", "company", "寒武纪")
    g.upsert_edge("ai_compute", "688256", "leader", weight=1.0)
    # 把 doc 也接到图上，模拟 mentioned_in
    g.upsert_node("d1", "document", "GPU 训练 模型 寒武纪")
    g.upsert_edge("688256", "d1", "mentioned_in", weight=0.5)
    extractor = RuleEntityExtractor(company_dict={"688256": "寒武纪"})
    graph_r = GraphNeighborRetriever(g, extractor, hops=2)

    hybrid = HybridRetriever([bm25, graph_r], rrf_k=10)
    hits = hybrid.search("寒武纪 GPU", top_k=5)
    assert hits
    assert all(h.evidence_chain for h in hits)


def test_tokenize_chinese_and_english_mixed():
    out = tokenize("GPU 训练 chips 寒武纪")
    assert "gpu" in out
    assert "chips" in out
    assert "训" in out and "练" in out
    assert "寒" in out


# --- 5. build_knowledge_graph 增量构建 + 幂等 ---


def test_build_knowledge_graph_idempotent(tmp_path, monkeypatch):
    db = tmp_path / "kg.db"
    # 准备一条新闻
    news_df = pd.DataFrame(
        {
            "title": ["寒武纪发布新一代 GPU 芯片"],
            "time": ["2024-05-01 09:00:00"],
            "url": ["https://example.com/n1"],
            "content": ["寒武纪 688256 发布新一代 GPU 芯片，进军 data_center 市场"],
        }
    )
    with get_connection(str(db)) as conn:
        NewsRepository(conn).upsert_dataframe(source="test", news=news_df)

    company_dict = {"688256": "寒武纪"}
    stats1 = build_kg_run(db_path=str(db), company_dict=company_dict)
    assert stats1["docs"] >= 1
    n1 = stats1["nodes_in_store"]
    e1 = stats1["edges_in_store"]
    assert n1 > 0 and e1 > 0

    # 二次运行应幂等（节点/边数不增加）
    stats2 = build_kg_run(db_path=str(db), company_dict=company_dict)
    assert stats2["nodes_in_store"] == n1
    assert stats2["edges_in_store"] == e1

    # 证据回链可查
    with get_connection(str(db)) as conn:
        ev = KnowledgeEvidenceRepository(conn).for_node("688256")
        assert ev and ev[0]["doc_source"] == "test"
