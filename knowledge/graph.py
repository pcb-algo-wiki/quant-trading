from __future__ import annotations


def build_industry_graph(taxonomy: dict, leaders: list[dict]) -> dict:
    nodes = {}
    edges = []

    for industry, cfg in taxonomy.items():
        nodes[industry] = {"id": industry, "type": "industry", "name": cfg.get("name", industry)}
        for layer in ("upstream", "midstream", "downstream"):
            for segment in cfg.get(layer, []):
                seg_id = f"{industry}:{layer}:{segment}"
                nodes[seg_id] = {"id": seg_id, "type": "segment", "name": segment, "layer": layer}
                edges.append({"source": industry, "target": seg_id, "type": "has_segment"})

    for leader in leaders:
        symbol = str(leader["symbol"])
        industry = str(leader["industry"])
        nodes[symbol] = {"id": symbol, "type": "company", "name": leader.get("name", symbol)}
        edges.append({"source": industry, "target": symbol, "type": "leader"})

    return {"nodes": nodes, "edges": edges}
