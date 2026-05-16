"""知识图谱存储后端（Phase 7）

提供两个可互换后端：
  - NetworkXBackend：基于 SQLite + NetworkX（无额外依赖，Phase 1 已有）
  - Neo4jBackend：基于 Neo4j（软导入 neo4j driver，无包/无服务时自动降级 NetworkX）

用法：
    from knowledge.graph_backends import get_graph_backend
    backend = get_graph_backend()   # 自动选择
    backend.upsert_node("半导体", "industry", {"score": 0.8})
    backend.upsert_edge("半导体", "先进制程", "has_segment")
    neighbors = backend.get_neighbors("半导体", hops=2)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 抽象接口
# ─────────────────────────────────────────────────────────────────────────────

class GraphBackend(ABC):
    """图谱后端统一接口。"""

    @abstractmethod
    def upsert_node(self, node_id: str, node_type: str, attrs: dict | None = None) -> None:
        """插入或更新节点。"""

    @abstractmethod
    def upsert_edge(
        self,
        src: str,
        dst: str,
        edge_type: str,
        weight: float = 1.0,
        evidence: dict | None = None,
    ) -> None:
        """插入或更新边（按 weight max 合并）。"""

    @abstractmethod
    def get_neighbors(self, node_id: str, hops: int = 1) -> list[str]:
        """BFS 召回 N 跳邻居节点 ID 列表。"""

    @abstractmethod
    def is_available(self) -> bool:
        """后端是否可用（连接可达 + 依赖已安装）。"""

    @abstractmethod
    def backend_name(self) -> str:
        """后端名称标识。"""


# ─────────────────────────────────────────────────────────────────────────────
# NetworkX 后端（Phase 1 基线，无额外依赖）
# ─────────────────────────────────────────────────────────────────────────────

class NetworkXBackend(GraphBackend):
    """内存图（NetworkX）+ SQLite 持久化后端。

    轻量可靠，适合单机本地场景。
    通过复用 knowledge.graph.IndustryGraph 实现。
    """

    def __init__(self) -> None:
        import networkx as nx
        self._g = nx.DiGraph()

    def upsert_node(self, node_id: str, node_type: str, attrs: dict | None = None) -> None:
        self._g.add_node(node_id, type=node_type, **(attrs or {}))

    def upsert_edge(
        self,
        src: str,
        dst: str,
        edge_type: str,
        weight: float = 1.0,
        evidence: dict | None = None,
    ) -> None:
        existing = self._g.get_edge_data(src, dst, default={})
        max_weight = max(existing.get("weight", 0.0), weight)
        self._g.add_edge(src, dst, type=edge_type, weight=max_weight)

    def get_neighbors(self, node_id: str, hops: int = 1) -> list[str]:
        if node_id not in self._g:
            return []
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}
        for _ in range(hops):
            next_frontier: set[str] = set()
            for n in frontier:
                for nb in self._g.successors(n):
                    if nb not in visited:
                        visited.add(nb)
                        next_frontier.add(nb)
            frontier = next_frontier
        visited.discard(node_id)
        return list(visited)

    def is_available(self) -> bool:
        try:
            import networkx  # noqa: F401
            return True
        except ImportError:
            return False

    def backend_name(self) -> str:
        return "networkx"


# ─────────────────────────────────────────────────────────────────────────────
# Neo4j 后端（Phase 7 重型升级，软导入）
# ─────────────────────────────────────────────────────────────────────────────

class Neo4jBackend(GraphBackend):
    """Neo4j 图数据库后端（Phase 7）。

    软导入 neo4j Python driver：
      - 有包且服务可达 → 真实 Neo4j Cypher 操作
      - 无包或连接失败 → 记录警告，`is_available()` 返回 False
        （调用者应检查 is_available() 并 fallback 到 NetworkXBackend）

    Args:
        uri: Neo4j bolt URI（默认 bolt://localhost:7687）
        user: 用户名
        password: 密码
        database: 数据库名（默认 neo4j）
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver = None
        self._available = False
        self._try_connect()

    def _try_connect(self) -> None:
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
            # 验证连接
            with self._driver.session(database=self._database) as session:
                session.run("RETURN 1")
            self._available = True
            logger.info("[Neo4j] 连接成功: %s db=%s", self._uri, self._database)
        except ImportError:
            logger.warning("[Neo4j] neo4j 包未安装（pip install neo4j），跳过")
        except Exception as exc:
            logger.warning("[Neo4j] 连接失败: %s", exc)

    def is_available(self) -> bool:
        return self._available

    def backend_name(self) -> str:
        return "neo4j"

    def upsert_node(self, node_id: str, node_type: str, attrs: dict | None = None) -> None:
        if not self._available:
            return
        attrs = attrs or {}
        with self._driver.session(database=self._database) as session:
            session.run(
                "MERGE (n:Node {node_id: $id}) "
                "SET n.type = $type, n += $attrs",
                id=node_id, type=node_type, attrs=attrs,
            )

    def upsert_edge(
        self,
        src: str,
        dst: str,
        edge_type: str,
        weight: float = 1.0,
        evidence: dict | None = None,
    ) -> None:
        if not self._available:
            return
        with self._driver.session(database=self._database) as session:
            session.run(
                "MATCH (a:Node {node_id: $src}), (b:Node {node_id: $dst}) "
                "MERGE (a)-[r:EDGE {type: $type}]->(b) "
                "SET r.weight = CASE WHEN r.weight > $w THEN r.weight ELSE $w END",
                src=src, dst=dst, type=edge_type, w=weight,
            )

    def get_neighbors(self, node_id: str, hops: int = 1) -> list[str]:
        if not self._available:
            return []
        with self._driver.session(database=self._database) as session:
            result = session.run(
                f"MATCH (n:Node {{node_id: $id}})-[*1..{hops}]->(m:Node) "
                "RETURN DISTINCT m.node_id AS neighbor",
                id=node_id,
            )
            return [r["neighbor"] for r in result]

    def close(self) -> None:
        if self._driver:
            self._driver.close()


# ─────────────────────────────────────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────────────────────────────────────

def get_graph_backend(prefer: str = "auto") -> GraphBackend:
    """返回可用的图谱后端。

    Args:
        prefer: "neo4j" | "networkx" | "auto"
            auto → 尝试 neo4j（读 config），失败则降级 networkx

    Returns:
        可用的 GraphBackend 实例
    """
    if prefer == "networkx":
        return NetworkXBackend()

    if prefer == "neo4j":
        b = _build_neo4j_from_cfg()
        if b.is_available():
            return b
        logger.warning("[graph_backends] Neo4j 不可用，降级为 NetworkX")
        return NetworkXBackend()

    # auto: 读 config 决定
    try:
        from utils.config import cfg
        backend_cfg = cfg.get("knowledge.graph_backend", "networkx") or "networkx"
    except Exception:
        backend_cfg = "networkx"

    if backend_cfg == "neo4j":
        b = _build_neo4j_from_cfg()
        if b.is_available():
            return b
        logger.warning("[graph_backends] Neo4j 不可用，降级为 NetworkX")

    return NetworkXBackend()


def _build_neo4j_from_cfg() -> Neo4jBackend:
    try:
        from utils.config import cfg
        neo4j_cfg = cfg.get("knowledge.neo4j", {}) or {}
        return Neo4jBackend(
            uri=neo4j_cfg.get("uri", "bolt://localhost:7687"),
            user=neo4j_cfg.get("user", "neo4j"),
            password=neo4j_cfg.get("password", "password"),
            database=neo4j_cfg.get("database", "neo4j"),
        )
    except Exception:
        return Neo4jBackend()
