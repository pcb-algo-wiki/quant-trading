#!/usr/bin/env python3
"""
scripts/build_vector_store.py
=============================
从 SQLite news_items 构建 TF-IDF + SVD 向量库（data/cache/vector_store/），
供 HybridRetriever 的 VectorRetriever 使用。

用法:
    python scripts/build_vector_store.py
    或在代码里: from scripts.build_vector_store import run; run()

输出:
    data/cache/vector_store/vector_store.npz
    data/cache/vector_store/vector_store.texts.json
    data/cache/vector_store/vector_store.extras.json
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge.vector_store import SemanticVectorStore


def build_news_vector_store_semantic() -> SemanticVectorStore:
    """从 SQLite news_items 构建 sentence-transformers 语义向量库。"""
    from data_store.db import get_connection

    store = SemanticVectorStore()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rowid, title, COALESCE(content, '') FROM news_items "
            "WHERE content NOT IN ('', 'nan', 'None') AND content IS NOT NULL "
            "ORDER BY published_at DESC LIMIT 500"
        ).fetchall()
        for row in rows:
            doc_id, title, content = row
            text = f"{title} {content}".strip()
            if text:
                store.index(str(doc_id), text, title=title)

    store.build_index()
    return store

VECTOR_STORE_DIR = Path("data/cache/vector_store")
VECTOR_STORE_PATH = VECTOR_STORE_DIR / "vector_store"


def run() -> dict:
    """构建并保存 sentence-transformers 语义向量库。"""
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)

    store = build_news_vector_store_semantic()
    store.save(VECTOR_STORE_PATH)

    hits = store.search("GPU 芯片", top_k=3)
    return {
        "docs_indexed": len(store._texts),
        "embedding_dim": store._vectors.shape[1] if store._vectors is not None else 0,
        "embedding_type": "semantic" if store._use_st else "tfidf",
        "path": str(VECTOR_STORE_PATH),
        "sample_hits": len(hits),
    }


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
