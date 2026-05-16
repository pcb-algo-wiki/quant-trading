"""图上 BFS 衰减情感传播

propagate_scores() 以种子节点分数为起点，每跳乘以 decay 系数，
向上下游扩散。种子节点分数不被覆盖（seed 优先）。

用法：
    from knowledge.graph import IndustryGraph
    graph = IndustryGraph()
    # ... 构建图 ...
    result = propagate_scores(graph, {"芯片": -0.8}, decay=0.5, max_hops=2)
    # -> {"芯片": -0.8, "半导体设备": -0.4, "封装测试": -0.2, ...}
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge.graph import IndustryGraph


def propagate_scores(
    graph: "IndustryGraph",
    seed_scores: dict[str, float],
    decay: float = 0.5,
    max_hops: int = 2,
) -> dict[str, float]:
    """BFS 衰减传播。

    Args:
        graph: IndustryGraph 实例（已加载节点和边）
        seed_scores: {node_id: 初始分数}，分数范围 [-1, 1]
        decay: 每跳衰减系数（0 < decay ≤ 1）
        max_hops: 最大传播跳数

    Returns:
        {node_id: propagated_score}（含种子节点；种子分数不被覆盖）
    """
    result: dict[str, float] = dict(seed_scores)
    current_frontier: dict[str, float] = dict(seed_scores)

    for _ in range(max(1, max_hops)):
        next_frontier: dict[str, float] = {}
        for node_id, score in current_frontier.items():
            propagated = score * decay
            for neighbor in graph.neighbors(node_id, hops=1):
                if neighbor in seed_scores:
                    continue  # seed 优先，不覆盖
                existing = result.get(neighbor, 0.0)
                if abs(propagated) > abs(existing):
                    next_frontier[neighbor] = propagated
        for node, val in next_frontier.items():
            if abs(val) > abs(result.get(node, 0.0)):
                result[node] = val
        current_frontier = next_frontier
        if not current_frontier:
            break

    return result


def build_industry_events(
    news_row: dict,
    sentiment_score: float,
    policy_score: float,
    propagated: dict[str, float],
) -> list[dict]:
    """将传播结果转化为 industry_events 格式的行列表。

    每个被传播到的节点产出一条 event 行；
    sentiment_score 和 policy_score 为共享元数据。
    """
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    events = []
    published_at = news_row.get("published_at", now)
    source = news_row.get("source", "unknown")
    title = news_row.get("title", "")

    for node_id, prop_score in propagated.items():
        events.append({
            "event_id": uuid.uuid4().hex,
            "event_type": "sentiment_propagation",
            "industry": node_id,
            "symbol": news_row.get("related_symbol"),
            "title": title,
            "score": round(prop_score, 4),
            "source": source,
            "published_at": published_at,
            "ingested_at": now,
            "sentiment_score": round(sentiment_score, 4),
            "policy_score": round(policy_score, 4),
            "propagated_score": round(prop_score, 4),
        })
    return events


def upsert_event_scores(conn, events: list[dict]) -> int:
    """幂等写入 industry_events（含三个新列）。返回 upserted 行数。"""
    count = 0
    for e in events:
        conn.execute(
            """
            INSERT OR REPLACE INTO industry_events
                (event_id, event_type, industry, symbol, title, score,
                 source, published_at, ingested_at,
                 sentiment_score, policy_score, propagated_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e["event_id"], e["event_type"], e.get("industry"),
                e.get("symbol"), e["title"], e["score"],
                e["source"], e.get("published_at"), e["ingested_at"],
                e.get("sentiment_score"), e.get("policy_score"),
                e.get("propagated_score"),
            ),
        )
        count += 1
    conn.commit()
    return count
