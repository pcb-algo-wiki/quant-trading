"""Phase 14.5 — 模型注册表 + 因子 IC 历史

设计：
- model_registry 表记录每个 (model_name, version) 的元信息和 metrics
- status: candidate / champion / archived
- promote 时自动把原 champion 降级为 archived
- factor_ic_history 表记录因子 IC 时序，用于漂移监控（Phase 15）
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from data_store import schema as _schema

# 注册扩展表
_EXTRA_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS model_registry (
        model_name TEXT NOT NULL,
        version INTEGER NOT NULL,
        model_type TEXT NOT NULL,
        features_json TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        artifact_path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'candidate',
        notes TEXT,
        created_at TEXT NOT NULL,
        promoted_at TEXT,
        PRIMARY KEY (model_name, version)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_model_status ON model_registry(model_name, status);",
    """
    CREATE TABLE IF NOT EXISTS factor_ic_history (
        factor_name TEXT NOT NULL,
        date TEXT NOT NULL,
        ic_value REAL NOT NULL,
        sample_size INTEGER,
        method TEXT NOT NULL DEFAULT 'pearson',
        created_at TEXT NOT NULL,
        PRIMARY KEY (factor_name, date, method)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_ic_factor_date ON factor_ic_history(factor_name, date);",
]


def _ensure_tables(conn: sqlite3.Connection) -> None:
    for stmt in _EXTRA_TABLES:
        conn.execute(stmt)
    conn.commit()


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


class ModelRegistry:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        _ensure_tables(conn)

    # ===== model registry =====

    def register_model(
        self,
        model_name: str,
        model_type: str,
        features: list[str],
        metrics: dict,
        artifact_path: str,
        notes: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM model_registry WHERE model_name = ?",
            (model_name,),
        )
        next_version = int(cur.fetchone()[0]) + 1
        self.conn.execute(
            """
            INSERT INTO model_registry
            (model_name, version, model_type, features_json, metrics_json,
             artifact_path, status, notes, created_at, promoted_at)
            VALUES (?, ?, ?, ?, ?, ?, 'candidate', ?, ?, NULL)
            """,
            (
                model_name, next_version, model_type,
                json.dumps(features, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False),
                artifact_path, notes, _now(),
            ),
        )
        return next_version

    def list_versions(self, model_name: str) -> list[dict]:
        cur = self.conn.execute(
            """
            SELECT model_name, version, model_type, features_json, metrics_json,
                   artifact_path, status, notes, created_at, promoted_at
            FROM model_registry WHERE model_name = ? ORDER BY version
            """,
            (model_name,),
        )
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def get_version(self, model_name: str, version: int) -> dict | None:
        cur = self.conn.execute(
            """
            SELECT model_name, version, model_type, features_json, metrics_json,
                   artifact_path, status, notes, created_at, promoted_at
            FROM model_registry WHERE model_name = ? AND version = ?
            """,
            (model_name, version),
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def get_latest(self, model_name: str) -> dict | None:
        cur = self.conn.execute(
            """
            SELECT model_name, version, model_type, features_json, metrics_json,
                   artifact_path, status, notes, created_at, promoted_at
            FROM model_registry WHERE model_name = ?
            ORDER BY version DESC LIMIT 1
            """,
            (model_name,),
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def get_champion(self, model_name: str) -> dict | None:
        cur = self.conn.execute(
            """
            SELECT model_name, version, model_type, features_json, metrics_json,
                   artifact_path, status, notes, created_at, promoted_at
            FROM model_registry WHERE model_name = ? AND status = 'champion'
            """,
            (model_name,),
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def promote(self, model_name: str, version: int) -> None:
        """把指定版本升为 champion；其它所有版本（含 candidate）归档。"""
        self.conn.execute(
            "UPDATE model_registry SET status='archived' "
            "WHERE model_name = ? AND version != ?",
            (model_name, version),
        )
        self.conn.execute(
            "UPDATE model_registry SET status='champion', promoted_at = ? "
            "WHERE model_name = ? AND version = ?",
            (_now(), model_name, version),
        )

    # ===== factor IC history =====

    def log_factor_ic(
        self,
        factor_name: str,
        date: str,
        ic_value: float,
        sample_size: int | None = None,
        method: str = "pearson",
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO factor_ic_history
            (factor_name, date, ic_value, sample_size, method, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (factor_name, date, ic_value, sample_size, method, _now()),
        )

    def fetch_factor_ic(self, factor_name: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT factor_name, date, ic_value, sample_size, method "
            "FROM factor_ic_history WHERE factor_name = ? ORDER BY date",
            (factor_name,),
        )
        return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        d["features"] = json.loads(d.pop("features_json"))
        d["metrics"] = json.loads(d.pop("metrics_json"))
        return d
