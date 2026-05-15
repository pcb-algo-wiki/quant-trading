#!/usr/bin/env python3
"""
构建行业龙头图谱（MVP）。
"""

from __future__ import annotations

import json
from pathlib import Path

from knowledge.graph import build_industry_graph
from knowledge.taxonomy import DEFAULT_TAXONOMY


def run(leaders: list[dict] | None = None, output_path: str = "results/graphs/industry_graph.json") -> dict:
    leaders = leaders or []
    graph = build_industry_graph(DEFAULT_TAXONOMY, leaders)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph


if __name__ == "__main__":
    result = run()
    print(f"nodes={len(result['nodes'])}, edges={len(result['edges'])}")
