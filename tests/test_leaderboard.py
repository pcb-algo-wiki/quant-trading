from research.leaderboard import rank_leaders


def test_rank_leaders_returns_sorted_scores():
    rows = [
        {"industry": "ai_compute", "symbol": "A", "momentum": 0.2, "fund_flow": 0.5, "event_score": 1.0},
        {"industry": "ai_compute", "symbol": "B", "momentum": 0.1, "fund_flow": 0.2, "event_score": 0.2},
    ]
    ranked = rank_leaders(rows)
    assert ranked[0]["symbol"] == "A"
    assert ranked[0]["score"] > ranked[1]["score"]
