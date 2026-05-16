#!/usr/bin/env python3
"""
知识图谱填充脚本 - 从行业事件构建知识节点+边并写入SQLite
"""
from __future__ import annotations

import sys, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_store.db import get_connection
from knowledge.graph import IndustryGraph
from knowledge.taxonomy import DEFAULT_TAXONOMY


def fill_knowledge_graph() -> dict:
    """从 taxonomy 构建行业知识图谱并写入 SQLite"""
    g = IndustryGraph()

    # 添加产业链 taxonomy
    g.add_taxonomy(DEFAULT_TAXONOMY)

    with get_connection() as conn:
        n_nodes, n_edges = g.save_to_store(conn)

    return {"nodes_saved": n_nodes, "edges_saved": n_edges}


if __name__ == "__main__":
    result = fill_knowledge_graph()
    print(result)
