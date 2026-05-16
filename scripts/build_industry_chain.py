#!/usr/bin/env python3
"""
scripts/build_industry_chain.py
===============================
将龙头公司、供应关系、政策节点写入知识图谱并同步到 wiki。

用法:
    python scripts/build_industry_chain.py
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_store.db import get_connection
from knowledge.graph import IndustryGraph
from knowledge.industry_chain import build_industry_chain


def run() -> dict:
    with get_connection() as conn:
        g = IndustryGraph.load_from_store(conn)
        print(f"Loaded graph: {g.node_count()} nodes, {g.edge_count()} edges")

        stats = build_industry_chain(g)
        print(f"Industry chain stats: {stats}")

        n, e = g.save_to_store(conn)
        print(f"Saved: {n} nodes, {e} edges")

    return stats


if __name__ == "__main__":
    result = run()
    print(result)
