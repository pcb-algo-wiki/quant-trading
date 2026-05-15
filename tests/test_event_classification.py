from research.classifiers import classify_event_type
from research.events import build_events_from_news


def test_classify_event_type_policy_positive():
    title = "工信部发布算力基础设施支持政策"
    event = classify_event_type(title=title, content="政策支持，推进落地")
    assert event["event_type"] == "policy_positive"
    assert event["score"] > 0


def test_build_events_from_news_extracts_industry_and_sentiment():
    rows = [
        {
            "source": "eastmoney",
            "title": "半导体设备订单大增",
            "content": "订单超预期，产业景气提升",
            "time": "2026-05-01 09:30:00",
            "情感得分": 0.8,
            "industry": "semiconductor",
            "symbol": "002371",
        }
    ]
    events = build_events_from_news(rows)
    assert len(events) == 1
    assert events[0]["industry"] == "semiconductor"
    assert events[0]["symbol"] == "002371"
