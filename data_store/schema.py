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
    # Phase 13.1 — 公司行为与复权因子
    """
    CREATE TABLE IF NOT EXISTS corporate_actions (
        symbol TEXT NOT NULL,
        ex_date TEXT NOT NULL,
        action_type TEXT NOT NULL,
        cash_dividend REAL NOT NULL DEFAULT 0.0,
        split_ratio REAL NOT NULL DEFAULT 1.0,
        source TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (symbol, ex_date, action_type, source)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_corp_actions_symbol ON corporate_actions(symbol, ex_date);",
    """
    CREATE TABLE IF NOT EXISTS adj_factors (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        adj_factor REAL NOT NULL,
        source TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (symbol, date, source)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_adj_factors_symbol ON adj_factors(symbol, date);",
    # Phase 13.3 — 增量数据源
    """
    CREATE TABLE IF NOT EXISTS northbound_flow (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        hold_shares REAL,
        hold_market_cap REAL,
        hold_ratio REAL,
        source TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (symbol, date, source)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_north_symbol ON northbound_flow(symbol, date);",
    """
    CREATE TABLE IF NOT EXISTS dragon_tiger (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        reason TEXT NOT NULL,
        buy_amount REAL,
        sell_amount REAL,
        net_amount REAL,
        source TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (symbol, date, reason, source)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_dt_symbol ON dragon_tiger(symbol, date);",
    """
    CREATE TABLE IF NOT EXISTS block_trades (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        price REAL,
        volume REAL,
        amount REAL,
        buyer TEXT,
        seller TEXT,
        source TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (symbol, date, price, volume, buyer, seller, source)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_block_symbol ON block_trades(symbol, date);",
    """
    CREATE TABLE IF NOT EXISTS etf_holdings (
        etf_symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        stock_symbol TEXT NOT NULL,
        weight REAL,
        shares REAL,
        source TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY (etf_symbol, date, stock_symbol, source)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_etf_holdings ON etf_holdings(etf_symbol, date);",
    """
    CREATE TABLE IF NOT EXISTS industry_classification (
        symbol TEXT NOT NULL,
        scheme TEXT NOT NULL,
        level1 TEXT,
        level2 TEXT,
        level3 TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (symbol, scheme)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_industry_l1 ON industry_classification(level1);",
    # Phase 13.4 — 数据 lineage
    """
    CREATE TABLE IF NOT EXISTS data_provenance (
        prov_id TEXT PRIMARY KEY,
        dataset TEXT NOT NULL,
        source TEXT NOT NULL,
        symbol_count INTEGER,
        row_count INTEGER,
        pipeline_run_id TEXT,
        extra_json TEXT,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_prov_dataset ON data_provenance(dataset, created_at);",
]


def create_schema(conn: sqlite3.Connection) -> None:
    for stmt in SCHEMA_STATEMENTS:
        conn.execute(stmt)
    conn.commit()


# Phase 3 + Phase 13.2 — 按表分组的幂等列迁移
MIGRATION_STATEMENTS: list[tuple[str, str, str]] = [
    ("industry_events", "policy_score",     "ALTER TABLE industry_events ADD COLUMN policy_score REAL;"),
    ("industry_events", "sentiment_score",  "ALTER TABLE industry_events ADD COLUMN sentiment_score REAL;"),
    ("industry_events", "propagated_score", "ALTER TABLE industry_events ADD COLUMN propagated_score REAL;"),
    ("financial_reports", "operating_cash_flow", "ALTER TABLE financial_reports ADD COLUMN operating_cash_flow REAL;"),
    ("financial_reports", "free_cash_flow",      "ALTER TABLE financial_reports ADD COLUMN free_cash_flow REAL;"),
    ("financial_reports", "capex",               "ALTER TABLE financial_reports ADD COLUMN capex REAL;"),
    ("financial_reports", "total_assets",        "ALTER TABLE financial_reports ADD COLUMN total_assets REAL;"),
    ("financial_reports", "total_equity",        "ALTER TABLE financial_reports ADD COLUMN total_equity REAL;"),
    ("financial_reports", "roe",                 "ALTER TABLE financial_reports ADD COLUMN roe REAL;"),
    ("financial_reports", "roic",                "ALTER TABLE financial_reports ADD COLUMN roic REAL;"),
]


def apply_migrations(conn: sqlite3.Connection) -> None:
    """幂等追加新列——按表分组检查后才 ADD COLUMN。"""
    by_table: dict[str, list[tuple[str, str]]] = {}
    for table, col, stmt in MIGRATION_STATEMENTS:
        by_table.setdefault(table, []).append((col, stmt))
    for table, items in by_table.items():
        cursor = conn.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col_name, stmt in items:
            if col_name not in existing_cols:
                conn.execute(stmt)
    conn.commit()
