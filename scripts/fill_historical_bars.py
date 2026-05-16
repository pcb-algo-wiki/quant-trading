#!/usr/bin/env python3
"""
将 pickle 缓存中的历史行情数据批量写入 SQLite market_bars 表
"""
from __future__ import annotations

import sys, pickle
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_store.db import get_connection


ETF_CODES = ["510300", "510500", "159915"]
PICKLE_FILES = {
    "510300": "data/cache/etf_510300.pkl",
    "510500": "data/cache/etf_510500.pkl",
    "159915": "data/cache/etf_159915.pkl",
}


def fill_historical_bars() -> dict:
    total = 0
    with get_connection() as conn:
        for code, path in PICKLE_FILES.items():
            p = Path(path)
            if not p.exists():
                print(f"[SKIP] {code}: {path} not found")
                continue

            df = pickle.load(open(p, "rb"))
            if df.empty:
                print(f"[SKIP] {code}: empty DataFrame")
                continue

            inserted = 0
            now = datetime.utcnow().replace(microsecond=0).isoformat()
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT OR IGNORE INTO market_bars
                    (symbol, date, open, high, low, close, volume, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        code,
                        str(row["date"])[:10],
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        float(row["volume"]),
                        "sina",
                        now,
                    ),
                )
                inserted += 1

            conn.commit()
            print(f"[{code}] upserted {inserted} bars ({df.index[0]} ~ {df.index[-1]})")
            total += inserted

    return {"total_bars": total}


if __name__ == "__main__":
    result = fill_historical_bars()
    print(f"Done: {result}")
