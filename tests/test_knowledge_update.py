from knowledge.cards import build_industry_card
from knowledge.models import KnowledgeDocument
from knowledge.updater import update_industry_cards


def test_build_industry_card_contains_sources_and_timestamp():
    docs = [
        KnowledgeDocument(
            source="eastmoney",
            title="AI算力订单增长",
            url="https://example.com/1",
            published_at="2026-05-01 10:00:00",
            content="订单增长，景气提升",
            tags=["ai_compute", "orders"],
        )
    ]
    card = build_industry_card(industry="ai_compute", documents=docs)
    assert card["industry"] == "ai_compute"
    assert card["updated_at"]
    assert card["sources"][0]["source"] == "eastmoney"


def test_update_industry_cards_group_by_industry_tag():
    docs = [
        KnowledgeDocument(
            source="sina",
            title="光通信景气",
            url="https://example.com/a",
            published_at="2026-05-01 10:00:00",
            content="需求提升",
            tags=["optical_comms"],
        ),
        KnowledgeDocument(
            source="sina",
            title="半导体设备国产替代",
            url="https://example.com/b",
            published_at="2026-05-01 11:00:00",
            content="国产替代加速",
            tags=["semiconductor"],
        ),
    ]

    cards = update_industry_cards(docs)
    assert "optical_comms" in cards
    assert "semiconductor" in cards
    assert cards["semiconductor"]["doc_count"] == 1
