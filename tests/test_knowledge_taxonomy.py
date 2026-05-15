from knowledge.taxonomy import DEFAULT_TAXONOMY, get_industry_layers, list_seed_industries


def test_seed_industries_cover_mvp_scope():
    seeds = list_seed_industries()
    assert "ai_compute" in seeds
    assert "gpu" in seeds
    assert "semiconductor" in seeds
    assert "optical_comms" in seeds


def test_industry_layers_are_hierarchical():
    layers = get_industry_layers("semiconductor")
    assert "upstream" in layers
    assert "midstream" in layers
    assert "downstream" in layers
    assert "materials" in layers["upstream"]
