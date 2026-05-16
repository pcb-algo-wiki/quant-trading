from __future__ import annotations

import sqlite3


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS market_bars (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        source TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (symbol, date, source)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS news_items (
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        published_at TEXT NOT NULL,
        url TEXT,
        content TEXT,
        content_hash TEXT NOT NULL,
        sentiment REAL,
        related_symbol TEXT,
        ingested_at TEXT NOT NULL,
        UNIQUE (source, content_hash)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS policy_items (
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        published_at TEXT NOT NULL,
        url TEXT,
        content TEXT,
        content_hash TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        UNIQUE (source, content_hash)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS financial_reports (
        symbol TEXT NOT NULL,
        report_period TEXT NOT NULL,
        revenue REAL,
        net_profit REAL,
        gross_margin REAL,
        rd_expense REAL,
        source TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (symbol, report_period, source)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fund_flow (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        main_net_inflow REAL,
        super_net_inflow REAL,
        source TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (symbol, date, source)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS industry_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        industry TEXT,
        symbol TEXT,
        title TEXT NOT NULL,
        score REAL,
        source TEXT NOT NULL,
        published_at TEXT,
        ingested_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS source_documents (
        doc_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        url TEXT,
        title TEXT,
        content_hash TEXT NOT NULL,
        published_at TEXT,
        ingested_at TEXT NOT NULL,
        UNIQUE (source, content_hash)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        run_id TEXT PRIMARY KEY,
        pipeline TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        error TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_nodes (
        node_id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        attrs_json TEXT,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_edges (
        src TEXT NOT NULL,
        dst TEXT NOT NULL,
        type TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 1.0,
        evidence_json TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (src, dst, type)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_evidence (
        node_id TEXT NOT NULL,
        doc_source TEXT NOT NULL,
        doc_hash TEXT NOT NULL,
        snippet TEXT,
        ts TEXT NOT NULL,
        PRIMARY KEY (node_id, doc_source, doc_hash)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_type ON knowledge_nodes(type);",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_edges_dst ON knowledge_edges(dst, type);",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_evidence_doc ON knowledge_evidence(doc_source, doc_hash);",
    """
    CREATE TABLE IF NOT EXISTS reconcile_reports (
        report_id TEXT PRIMARY KEY,
        date TEXT NOT NULL,
        is_clean INTEGER NOT NULL DEFAULT 1,
        unmatched_signals_json TEXT,
        unmatched_trades_json TEXT,
        position_drift_json TEXT,
        notes TEXT,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_reconcile_date ON reconcile_reports(date);",
]


def create_schema(conn: sqlite3.Connection) -> None:
    for stmt in SCHEMA_STATEMENTS:
        conn.execute(stmt)
    conn.commit()


# Phase 3 — industry_events 列迁移（幂等：PRAGMA 检查后才执行 ALTER TABLE）
MIGRATION_STATEMENTS = [
    ("policy_score",     "ALTER TABLE industry_events ADD COLUMN policy_score REAL;"),
    ("sentiment_score",  "ALTER TABLE industry_events ADD COLUMN sentiment_score REAL;"),
    ("propagated_score", "ALTER TABLE industry_events ADD COLUMN propagated_score REAL;"),
]


def apply_migrations(conn: sqlite3.Connection) -> None:
    """幂等追加新列——若列已存在则跳过（SQLite 重复 ADD COLUMN 会报 OperationalError）。"""
    cursor = conn.execute("PRAGMA table_info(industry_events)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    for col_name, stmt in MIGRATION_STATEMENTS:
        if col_name not in existing_cols:
            conn.execute(stmt)
    conn.commit()
