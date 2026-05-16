"""Phase 3 政策挖掘与情感传导测试"""
from __future__ import annotations

import sqlite3
import pytest


# ── 任务 1：Schema 迁移 ──────────────────────────────────────────────────────

def test_migration_adds_columns(tmp_path):
    """apply_migrations 在 industry_events 上追加 3 列"""
    from data_store.schema import create_schema, apply_migrations

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    create_schema(conn)
    apply_migrations(conn)

    cursor = conn.execute("PRAGMA table_info(industry_events)")
    cols = {row[1] for row in cursor.fetchall()}
    assert "policy_score" in cols
    assert "sentiment_score" in cols
    assert "propagated_score" in cols
    conn.close()


def test_migration_is_idempotent(tmp_path):
    """apply_migrations 二次调用不报错，列数不变"""
    from data_store.schema import create_schema, apply_migrations

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    create_schema(conn)
    apply_migrations(conn)
    apply_migrations(conn)  # 第二次调用应静默成功

    cursor = conn.execute("PRAGMA table_info(industry_events)")
    cols = [row[1] for row in cursor.fetchall()]
    # policy_score 只出现一次
    assert cols.count("policy_score") == 1
    conn.close()


# ── 任务 2：政策摄取 ──────────────────────────────────────────────────────────

def test_policy_fetch_fallback_to_seed():
    """AkShare 失败时降级到种子数据，返回非空列表"""
    from data.policy.fifteenth_five_year import fetch_policy_articles
    from unittest.mock import patch

    with patch("data.policy.fifteenth_five_year._try_akshare", return_value=[]):
        result = fetch_policy_articles()
    assert isinstance(result, list)
    assert len(result) >= 1
    assert "title" in result[0]


def test_policy_ingest_idempotent(tmp_path):
    """重复摄取同一条政策，只插入一次"""
    import sqlite3
    from data_store.schema import create_schema, apply_migrations
    from data.policy.fifteenth_five_year import ingest_policy_articles

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    apply_migrations(conn)

    articles = [{"title": "测试政策", "content": "内容", "url": "", "published_at": "2026-01-01", "source": "test", "content_hash": "abc123"}]
    r1 = ingest_policy_articles(conn, articles)
    r2 = ingest_policy_articles(conn, articles)

    assert r1["inserted"] == 1
    assert r2["inserted"] == 0 and r2["skipped"] == 1
    conn.close()


def test_policy_keyword_filter():
    """keyword 过滤：只返回包含关键词的文章"""
    from data.policy.fifteenth_five_year import fetch_policy_articles
    from unittest.mock import patch

    seed = [
        {"title": "新能源政策", "content": "光伏发展", "url": "", "published_at": "2026-01-01", "source": "s"},
        {"title": "金融监管", "content": "银行规定", "url": "", "published_at": "2026-01-01", "source": "s"},
    ]
    with patch("data.policy.fifteenth_five_year._try_akshare", return_value=[]):
        with patch("data.policy.fifteenth_five_year._load_seed", return_value=seed):
            result = fetch_policy_articles(keywords=["新能源"])
    # 匹配到 1 条
    assert any("新能源" in a["title"] for a in result)


# ── 任务 3：情感分析 ──────────────────────────────────────────────────────────

def test_sentiment_positive_text():
    """明确利好文本的 analyze 结果 > 0"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend()
    score = backend.analyze("公司业绩超预期大幅增长，股价涨停，订单大量增加")
    assert score > 0, f"expected > 0, got {score}"


def test_sentiment_negative_text():
    """明确利空文本的 analyze 结果 < 0"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend()
    score = backend.analyze("公司因违规被调查，业绩亏损扩大，面临退市风险")
    assert score < 0, f"expected < 0, got {score}"


def test_sentiment_empty_text():
    """空文本返回 0.0"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend()
    assert backend.analyze("") == 0.0
    assert backend.analyze("   ") == 0.0


def test_sentiment_clamp_in_range():
    """analyze 结果始终在 [-1, 1] 范围内"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend(
        pos_terms=["涨涨涨"] * 10,
        neg_terms=[],
    )
    score = backend.analyze("涨涨涨涨涨涨涨")
    assert -1.0 <= score <= 1.0


# ── 任务 4：政策对齐 ──────────────────────────────────────────────────────────

def test_policy_aligner_basic():
    """相关文本的 score > 不相关文本的 score"""
    from research.policy_alignment import PolicyAligner
    aligner = PolicyAligner().fit([
        "推动新能源汽车产业发展，支持光伏和储能技术创新",
        "加强半导体芯片自主研发，推进集成电路产业升级",
    ])
    score_relevant = aligner.score("公司专注新能源电池和光伏组件制造")
    score_irrelevant = aligner.score("餐饮连锁门店扩张，主营烤鸭和火锅")
    assert score_relevant > score_irrelevant


def test_policy_aligner_empty_corpus():
    """空语料时 score 返回 0.0"""
    from research.policy_alignment import PolicyAligner
    aligner = PolicyAligner().fit([])
    assert aligner.score("任意文本") == 0.0


def test_policy_aligner_score_in_range():
    """score 始终在 [0, 1] 范围内"""
    from research.policy_alignment import PolicyAligner
    aligner = PolicyAligner().fit(["政策文本一", "政策文本二"])
    score = aligner.score("查询文本")
    assert 0.0 <= score <= 1.0


# ── 任务 5：BFS 传播 ──────────────────────────────────────────────────────────

def _make_test_graph():
    """构建最小测试图：芯片 → 半导体设备 → 封装测试"""
    from knowledge.graph import IndustryGraph
    g = IndustryGraph()
    g.upsert_node("芯片", "industry", "芯片行业")
    g.upsert_node("半导体设备", "segment", "半导体设备")
    g.upsert_node("封装测试", "segment", "封装测试")
    g.upsert_edge("芯片", "半导体设备", "has_segment", weight=0.9)
    g.upsert_edge("芯片", "封装测试", "has_segment", weight=0.8)
    return g


def test_propagation_single_hop():
    """单跳传播：邻居节点得到 seed * decay"""
    from research.propagation import propagate_scores
    g = _make_test_graph()
    result = propagate_scores(g, {"芯片": -0.8}, decay=0.5, max_hops=1)
    assert "半导体设备" in result
    assert abs(result["半导体设备"] - (-0.4)) < 1e-9


def test_propagation_seed_not_overwritten():
    """种子节点的分数不被传播覆盖"""
    from research.propagation import propagate_scores
    g = _make_test_graph()
    g.upsert_node("消费电子", "segment", "消费电子")
    g.upsert_edge("芯片", "消费电子", "has_segment", weight=0.7)
    seeds = {"芯片": -0.8, "封装测试": 0.5}
    result = propagate_scores(g, seeds, decay=0.5, max_hops=2)
    # 封装测试是 seed，不应被 芯片 传播结果覆盖
    assert result["封装测试"] == 0.5


def test_propagation_isolated_node():
    """孤立节点不会被传播影响"""
    from research.propagation import propagate_scores
    from knowledge.graph import IndustryGraph
    g = IndustryGraph()
    g.upsert_node("芯片", "industry", "芯片行业")
    g.upsert_node("孤立节点", "industry", "孤立的")
    result = propagate_scores(g, {"芯片": -0.8}, decay=0.5, max_hops=2)
    assert "孤立节点" not in result


def test_upsert_event_scores(tmp_path):
    """upsert_event_scores 写入 industry_events 含三新列"""
    import sqlite3
    from data_store.schema import create_schema, apply_migrations
    from research.propagation import upsert_event_scores

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    apply_migrations(conn)

    events = [{
        "event_id": "test001",
        "event_type": "sentiment_propagation",
        "industry": "芯片",
        "symbol": None,
        "title": "半导体行业负面消息",
        "score": -0.4,
        "source": "test",
        "published_at": "2026-01-01",
        "ingested_at": "2026-01-01T00:00:00",
        "sentiment_score": -0.8,
        "policy_score": 0.6,
        "propagated_score": -0.4,
    }]
    count = upsert_event_scores(conn, events)
    assert count == 1

    row = conn.execute("SELECT * FROM industry_events WHERE event_id='test001'").fetchone()
    assert row is not None
    assert abs(row["sentiment_score"] - (-0.8)) < 1e-6
    assert abs(row["policy_score"] - 0.6) < 1e-6
    conn.close()


# ── 任务 6：daily_pipeline feature flag + 重放脚本 ────────────────────────────

def test_daily_pipeline_sentiment_flag_off():
    """sentiment.enabled=False 时 daily_pipeline 不调用 run_sentiment_replay"""
    from unittest.mock import patch

    with patch("scripts.daily_pipeline.update_data_store_run", return_value={}), \
         patch("scripts.daily_pipeline.update_knowledge_run", return_value={}), \
         patch("scripts.daily_pipeline.update_events_run", return_value={}), \
         patch("scripts.daily_pipeline.train_ml_run", return_value={}), \
         patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={}), \
         patch("research.report_builder.build_daily_summary", return_value="ok"):
        from scripts.daily_pipeline import run_daily_pipeline
        result = run_daily_pipeline()
    assert "sentiment" not in result


def test_sentiment_replay_dry_run(tmp_path):
    """dry_run=True 时不向数据库写入任何行"""
    import sqlite3
    from data_store.schema import create_schema, apply_migrations
    from unittest.mock import patch

    db_path = tmp_path / "test.db"
    conn_setup = sqlite3.connect(str(db_path))
    create_schema(conn_setup)
    apply_migrations(conn_setup)
    conn_setup.execute(
        "INSERT INTO news_items (source, title, published_at, content_hash, ingested_at) "
        "VALUES ('test', '测试利好消息', '2026-01-01', 'hash001', '2026-01-01T00:00:00')"
    )
    conn_setup.commit()
    conn_setup.close()

    with patch("data_store.db.DEFAULT_DB_PATH", db_path):
        from scripts.run_sentiment_replay import run
        result = run(start_date="2026-01-01", dry_run=True)

    assert result["processed"] >= 1
    assert result["inserted"] == 0

    conn_check = sqlite3.connect(str(db_path))
    count = conn_check.execute("SELECT COUNT(*) FROM industry_events").fetchone()[0]
    conn_check.close()
    assert count == 0
