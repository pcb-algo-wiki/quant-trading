"""Phase 17.5 — 审计 trace

为信号 → 订单 → 成交 → 对账 链路提供 trace_id 持久化。
"""
from __future__ import annotations

import json
import sqlite3
import uuid


_DDL = """
CREATE TABLE IF NOT EXISTS audit_trace (
    trace_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    stage TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trace_id, seq)
)
"""


class AuditTrace:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.execute(_DDL)
        conn.commit()

    @staticmethod
    def new_trace_id() -> str:
        return uuid.uuid4().hex[:16]

    def log(self, trace_id: str, stage: str, payload: dict) -> None:
        cur = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM audit_trace WHERE trace_id=?",
            (trace_id,),
        )
        next_seq = int(cur.fetchone()[0]) + 1
        self.conn.execute(
            "INSERT INTO audit_trace(trace_id, seq, stage, payload_json) "
            "VALUES (?,?,?,?)",
            (trace_id, next_seq, stage, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()

    def get_chain(self, trace_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT seq, stage, payload_json, created_at FROM audit_trace "
            "WHERE trace_id=? ORDER BY seq",
            (trace_id,),
        )
        return [
            {
                "seq": r[0],
                "stage": r[1],
                "payload": json.loads(r[2]),
                "created_at": r[3],
            }
            for r in cur.fetchall()
        ]
