from research.continuous_optimization import OptimizationManager


def test_optimization_manager_prioritizes_high_drift_items():
    mgr = OptimizationManager()
    backlog = [
        {"item": "news-parser", "drift_score": 0.2, "impact_score": 0.6},
        {"item": "ml-model", "drift_score": 0.8, "impact_score": 0.9},
    ]
    ranked = mgr.prioritize(backlog)
    assert ranked[0]["item"] == "ml-model"
