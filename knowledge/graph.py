"""
knowledge.graph
===============
Phase 1 GraphRAG MVP — 基于 NetworkX 的 IndustryGraph，可持久化到 data_store
SQLite 中的 knowledge_nodes / knowledge_edges 两表。

设计原则：
- 内存图采用 NetworkX DiGraph，方便 BFS / 邻居召回。
- 持久化以 SQLite 为单一真相源（SSOT）；图对象可以随时 load_from_store。
- upsert 语义：同 (src,dst,type) 的边按权重 max 合并；同 node_id 的节点按
  attrs 合并 + bump updated_at。
- 向后兼容：保留模块级函数 ``build_industry_graph(taxonomy, leaders) -> dict``。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import networkx as nx


VALID_NODE_TYPES = {"industry", "segment", "company", "policy", "document"}
VALID_EDGE_TYPES = {
    "has_segment",
    "leader",
    "supplier_of",
    "mentioned_in",
    "affected_by",
}


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


@dataclass
class NodeRef:
    node_id: str
    type: str
    name: str


class IndustryGraph:
    """轻量 GraphRAG 内存图 + SQLite 持久化。"""

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()

    # ---------- 基础写入 ----------

    def upsert_node(self, node_id: str, type: str, name: str, **attrs) -> None:
        if type not in VALID_NODE_TYPES:
            raise ValueError(f"invalid node type: {type}")
        if self._g.has_node(node_id):
            data = self._g.nodes[node_id]
            data["name"] = name or data.get("name") or node_id
            merged_attrs = dict(data.get("attrs") or {})
            merged_attrs.update(attrs)
            data["attrs"] = merged_attrs
            data["updated_at"] = _now()
        else:
            self._g.add_node(
                node_id,
                type=type,
                name=name or node_id,
                attrs=dict(attrs),
                updated_at=_now(),
            )

    def upsert_edge(
        self,
        src: str,
        dst: str,
        type: str,
        weight: float = 1.0,
        evidence: list[dict] | None = None,
    ) -> None:
        if type not in VALID_EDGE_TYPES:
            raise ValueError(f"invalid edge type: {type}")
        if not self._g.has_node(src) or not self._g.has_node(dst):
            raise KeyError(f"upsert_edge requires both nodes present: {src} -> {dst}")
        weight = max(0.0, min(1.0, float(weight)))
        key = (src, dst, type)
        if self._g.has_edge(src, dst) and self._g[src][dst].get("type") == type:
            data = self._g[src][dst]
            data["weight"] = max(float(data.get("weight", 0.0)), weight)
            if evidence:
                existing = list(data.get("evidence") or [])
                existing.extend(evidence)
                data["evidence"] = existing
            data["updated_at"] = _now()
        else:
            # 简化：单条 (src,dst) 仅保留首个 type 边；不同 type 用 (dst, type) 区分
            self._g.add_edge(
                src,
                dst,
                type=type,
                weight=weight,
                evidence=list(evidence or []),
                updated_at=_now(),
                _key=key,
            )

    # ---------- 查询 ----------

    def has_node(self, node_id: str) -> bool:
        return self._g.has_node(node_id)

    def get_node(self, node_id: str) -> dict | None:
        if not self._g.has_node(node_id):
            return None
        d = dict(self._g.nodes[node_id])
        d["node_id"] = node_id
        return d

    def neighbors(
        self,
        node_id: str,
        hops: int = 1,
        edge_types: Iterable[str] | None = None,
    ) -> list[str]:
        """BFS k 跳邻居（无向视角），可按 edge_types 过滤。"""
        if not self._g.has_node(node_id):
            return []
        allowed = set(edge_types) if edge_types else None
        visited = {node_id}
        frontier = {node_id}
        for _ in range(max(1, hops)):
            next_frontier: set[str] = set()
            for n in frontier:
                for _, dst, data in self._g.out_edges(n, data=True):
                    if allowed is None or data.get("type") in allowed:
                        if dst not in visited:
                            next_frontier.add(dst)
                for src, _, data in self._g.in_edges(n, data=True):
                    if allowed is None or data.get("type") in allowed:
                        if src not in visited:
                            next_frontier.add(src)
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        visited.discard(node_id)
        return sorted(visited)

    def node_count(self) -> int:
        return self._g.number_of_nodes()

    def edge_count(self) -> int:
        return self._g.number_of_edges()

    # ---------- 高级构建 ----------

    def add_taxonomy(self, taxonomy: dict) -> None:
        for industry, cfg in taxonomy.items():
            self.upsert_node(industry, "industry", cfg.get("name", industry))
            for layer in ("upstream", "midstream", "downstream"):
                for segment in cfg.get(layer, []) or []:
                    seg_id = f"{industry}:{layer}:{segment}"
                    self.upsert_node(seg_id, "segment", segment, layer=layer)
                    self.upsert_edge(industry, seg_id, "has_segment", weight=1.0)

    def add_leader(self, industry: str, symbol: str, name: str | None = None) -> None:
        self.upsert_node(symbol, "company", name or symbol)
        if self._g.has_node(industry):
            self.upsert_edge(industry, symbol, "leader", weight=1.0)

    # ---------- 持久化 ----------

    def save_to_store(self, conn: sqlite3.Connection) -> tuple[int, int]:
        node_n = 0
        edge_n = 0
        for nid, data in self._g.nodes(data=True):
            conn.execute(
                """
                INSERT INTO knowledge_nodes (node_id, type, name, attrs_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    type=excluded.type,
                    name=excluded.name,
                    attrs_json=excluded.attrs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    nid,
                    data.get("type", "company"),
                    data.get("name", nid),
                    json.dumps(data.get("attrs") or {}, ensure_ascii=False),
                    data.get("updated_at") or _now(),
                ),
            )
            node_n += 1
        for src, dst, data in self._g.edges(data=True):
            conn.execute(
                """
                INSERT INTO knowledge_edges (src, dst, type, weight, evidence_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(src, dst, type) DO UPDATE SET
                    weight=MAX(knowledge_edges.weight, excluded.weight),
                    evidence_json=excluded.evidence_json,
                    updated_at=excluded.updated_at
                """,
                (
                    src,
                    dst,
                    data.get("type", "mentioned_in"),
                    float(data.get("weight", 1.0)),
                    json.dumps(data.get("evidence") or [], ensure_ascii=False),
                    data.get("updated_at") or _now(),
                ),
            )
            edge_n += 1
        conn.commit()
        return node_n, edge_n

    @classmethod
    def load_from_store(cls, conn: sqlite3.Connection) -> "IndustryGraph":
        g = cls()
        for row in conn.execute(
            "SELECT node_id, type, name, attrs_json, updated_at FROM knowledge_nodes"
        ):
            attrs = json.loads(row["attrs_json"] or "{}")
            g._g.add_node(
                row["node_id"],
                type=row["type"],
                name=row["name"],
                attrs=attrs,
                updated_at=row["updated_at"],
            )
        for row in conn.execute(
            "SELECT src, dst, type, weight, evidence_json, updated_at FROM knowledge_edges"
        ):
            ev = json.loads(row["evidence_json"] or "[]")
            g._g.add_edge(
                row["src"],
                row["dst"],
                type=row["type"],
                weight=float(row["weight"]),
                evidence=ev,
                updated_at=row["updated_at"],
            )
        return g

    # ---------- 向后兼容 ----------

    def to_dict(self) -> dict:
        nodes: dict[str, dict] = {}
        for nid, data in self._g.nodes(data=True):
            item = {"id": nid, "type": data.get("type"), "name": data.get("name", nid)}
            attrs = data.get("attrs") or {}
            for k in ("layer",):
                if k in attrs:
                    item[k] = attrs[k]
            nodes[nid] = item
        edges = [
            {"source": s, "target": d, "type": data.get("type")}
            for s, d, data in self._g.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}


def build_industry_graph(taxonomy: dict, leaders: list[dict]) -> dict:
    """向后兼容旧 API：构建并返回 ``{nodes, edges}`` 字典。"""
    g = IndustryGraph()
    g.add_taxonomy(taxonomy)
    for leader in leaders or []:
        g.add_leader(
            industry=str(leader["industry"]),
            symbol=str(leader["symbol"]),
            name=leader.get("name"),
        )
    return g.to_dict()
