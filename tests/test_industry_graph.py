from knowledge.graph import build_industry_graph


def test_build_industry_graph_creates_nodes_and_edges():
    taxonomy = {
        "ai_compute": {
            "name": "AI算力",
            "upstream": ["chips"],
            "midstream": ["servers"],
            "downstream": ["training"],
        }
    }
    leaders = [{"industry": "ai_compute", "symbol": "688256", "name": "寒武纪"}]
    graph = build_industry_graph(taxonomy=taxonomy, leaders=leaders)

    assert "ai_compute" in graph["nodes"]
    assert "688256" in graph["nodes"]
    assert any(e["source"] == "ai_compute" and e["target"] == "688256" for e in graph["edges"])
