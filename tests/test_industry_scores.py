from research.industry_scores import score_industries


def test_score_industries_aggregates_event_scores():
    events = [
        {"industry": "ai_compute", "score": 1.2},
        {"industry": "ai_compute", "score": 0.8},
        {"industry": "semiconductor", "score": -0.5},
    ]
    result = score_industries(events)
    assert result["ai_compute"]["event_count"] == 2
    assert result["ai_compute"]["score"] > result["semiconductor"]["score"]
