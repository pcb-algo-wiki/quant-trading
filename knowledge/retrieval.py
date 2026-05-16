"""
knowledge.retrieval
===================
Phase 1 HybridRetriever：BM25（自实现） + 图邻居召回 + RRF 融合。

- ``BM25Retriever``：传统 BM25Okapi 算法，仅依赖 math / collections，避免引入
  rank_bm25 / elasticsearch。
- ``GraphNeighborRetriever``：基于 ``IndustryGraph`` 的 k 跳邻居召回；命中的实体
  节点扩展到与之相邻的文档节点。
- ``HybridRetriever.search`` 用 Reciprocal Rank Fusion (RRF) 融合多路 ranker，
  并保留 evidence_chain 回链。
- ``VectorRetriever`` 仅留接口占位，Phase 7 实装。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from knowledge.extractors import EntityExtractor, ExtractionResult
from knowledge.graph import IndustryGraph


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """轻量 tokenizer：英数连续段 + 中文按单字。"""
    if not text:
        return []
    return [t.lower() for t in _TOKEN_PATTERN.findall(text)]


@dataclass
class Document:
    doc_id: str
    text: str
    source: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Hit:
    doc_id: str
    score: float
    source: str = ""
    evidence_chain: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class Retriever(Protocol):
    def search(self, query: str, top_k: int = 10) -> list[Hit]: ...


# ---------- BM25 ----------


class BM25Retriever:
    def __init__(self, documents: list[Document], k1: float = 1.5, b: float = 0.75) -> None:
        self.documents = documents
        self.k1 = k1
        self.b = b
        self._tokens: list[list[str]] = [tokenize(d.text) for d in documents]
        self._doc_len = [len(t) for t in self._tokens]
        self._avgdl = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0
        df: Counter[str] = Counter()
        for tokens in self._tokens:
            for term in set(tokens):
                df[term] += 1
        self._df = df
        n = len(documents)
        self._idf = {
            term: math.log(1 + (n - cnt + 0.5) / (cnt + 0.5)) for term, cnt in df.items()
        }

    def search(self, query: str, top_k: int = 10) -> list[Hit]:
        q_tokens = tokenize(query)
        if not q_tokens or not self.documents:
            return []
        scores: list[tuple[int, float]] = []
        for idx, doc_tokens in enumerate(self._tokens):
            score = 0.0
            tf = Counter(doc_tokens)
            dl = self._doc_len[idx] or 1
            for term in q_tokens:
                if term not in tf:
                    continue
                idf = self._idf.get(term, 0.0)
                num = tf[term] * (self.k1 + 1)
                denom = tf[term] + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1))
                score += idf * (num / denom)
            if score > 0:
                scores.append((idx, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        out: list[Hit] = []
        for idx, s in scores[:top_k]:
            d = self.documents[idx]
            out.append(
                Hit(
                    doc_id=d.doc_id,
                    score=s,
                    source=d.source,
                    evidence_chain=[f"bm25:{d.doc_id}"],
                    extra=dict(d.extra),
                )
            )
        return out


# ---------- Graph neighbor retriever ----------


class GraphNeighborRetriever:
    """召回逻辑：
    1. extractor 抽取查询中的实体节点；
    2. 在 graph 上取 hops 跳邻居；
    3. 邻居节点（type=document）作为文档候选；其它实体节点暴露在 evidence_chain。
    """

    def __init__(
        self,
        graph: IndustryGraph,
        extractor: EntityExtractor,
        hops: int = 2,
    ) -> None:
        self.graph = graph
        self.extractor = extractor
        self.hops = max(1, hops)

    def search(self, query: str, top_k: int = 10) -> list[Hit]:
        ex: ExtractionResult = self.extractor.extract(query)
        seeds = list(set(ex.companies + ex.segments + ex.industries))
        if not seeds:
            return []

        scored: dict[str, tuple[float, list[str]]] = {}
        for seed in seeds:
            if not self.graph.has_node(seed):
                continue
            for hop_idx in range(1, self.hops + 1):
                neighbors = self.graph.neighbors(seed, hops=hop_idx)
                for n in neighbors:
                    node = self.graph.get_node(n) or {}
                    if node.get("type") != "document":
                        continue
                    decay = 1.0 / hop_idx
                    prev_score, prev_chain = scored.get(n, (0.0, []))
                    new_score = prev_score + decay
                    chain = prev_chain or [f"seed:{seed}", f"hops:{hop_idx}"]
                    scored[n] = (new_score, chain)

        hits = [
            Hit(
                doc_id=nid,
                score=s,
                source="graph",
                evidence_chain=chain + [f"node:{nid}"],
            )
            for nid, (s, chain) in scored.items()
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]


# ---------- Vector placeholder ----------


class VectorRetriever:
    """Phase 7 占位：未配置向量库时直接返回空。"""

    def search(self, query: str, top_k: int = 10) -> list[Hit]:  # noqa: ARG002
        return []


# ---------- Hybrid (RRF) ----------


def rrf_fuse(rankings: list[list[Hit]], k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion：score = sum(1 / (k + rank))。"""
    table: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            contrib = 1.0 / (k + rank)
            if hit.doc_id in table:
                base = table[hit.doc_id]
                base.score += contrib
                seen = set(base.evidence_chain)
                for ev in hit.evidence_chain:
                    if ev not in seen:
                        base.evidence_chain.append(ev)
                        seen.add(ev)
            else:
                table[hit.doc_id] = Hit(
                    doc_id=hit.doc_id,
                    score=contrib,
                    source=hit.source,
                    evidence_chain=list(hit.evidence_chain),
                    extra=dict(hit.extra),
                )
    fused = sorted(table.values(), key=lambda h: h.score, reverse=True)
    return fused


class HybridRetriever:
    def __init__(
        self,
        retrievers: Iterable[Retriever],
        rrf_k: int = 60,
    ) -> None:
        self.retrievers = list(retrievers)
        self.rrf_k = rrf_k

    def search(self, query: str, top_k: int = 10) -> list[Hit]:
        rankings = [r.search(query, top_k=top_k) for r in self.retrievers]
        fused = rrf_fuse(rankings, k=self.rrf_k)
        return fused[:top_k]
