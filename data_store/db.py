from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from data_store.schema import create_schema, apply_migrations


DEFAULT_DB_PATH = Path("data/cache/quant_data.db")


@contextmanager
def get_connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    apply_migrations(conn)   # Phase 3: 追加 industry_events 新列
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
