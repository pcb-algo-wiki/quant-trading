"""Phase 17.4 — 配置版本化

每次 daily_pipeline 启动时记录当前 yaml 快照（按内容 hash 去重）。
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Optional


_DDL = """
CREATE TABLE IF NOT EXISTS config_history (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT UNIQUE NOT NULL,
    yaml_content TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


class ConfigHistory:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.execute(_DDL)
        conn.commit()

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def snapshot(self, yaml_content: str, note: str = "") -> int:
        """记录快照；若内容已存在则返回原 snapshot_id。"""
        h = self._hash(yaml_content)
        existing = self.conn.execute(
            "SELECT snapshot_id FROM config_history WHERE content_hash=?", (h,)
        ).fetchone()
        if existing:
            return int(existing[0])
        cur = self.conn.execute(
            "INSERT INTO config_history(content_hash, yaml_content, note) VALUES (?,?,?)",
            (h, yaml_content, note),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_latest(self) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT snapshot_id, content_hash, yaml_content, note, created_at "
            "FROM config_history ORDER BY snapshot_id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {
            "snapshot_id": row[0],
            "content_hash": row[1],
            "yaml_content": row[2],
            "note": row[3],
            "created_at": row[4],
        }
