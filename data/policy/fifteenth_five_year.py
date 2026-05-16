"""政策文本摄取

策略：
1. 优先调用 AkShare（如支持政策类接口则用，否则跳过）
2. 网络失败时从 data/cache/policy_seed.json 加载种子数据
3. 写入 policy_items（幂等：content_hash UNIQUE）
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

SEED_PATH = Path(__file__).parent.parent / "cache" / "policy_seed.json"
CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _hash_content(title: str, content: str) -> str:
    return hashlib.md5(f"{title}{content}".encode("utf-8")).hexdigest()


def fetch_policy_articles(
    keywords: Optional[list[str]] = None,
    source: str = "gov_seed",
    max_items: int = 100,
) -> list[dict]:
    """抓取政策文章列表；网络失败时降级到 SEED_PATH。

    Returns:
        list of {title, content, url, published_at, content_hash, source}
    """
    articles = _try_akshare(keywords or [], max_items)

    if not articles:
        articles = _load_seed()

    if keywords:
        filtered = [
            a for a in articles
            if any(kw in (a.get("title", "") + a.get("content", "")) for kw in keywords)
        ]
        articles = filtered or articles  # 无匹配时返回全量种子

    for a in articles:
        a.setdefault("content_hash", _hash_content(a.get("title", ""), a.get("content", "")))
        a.setdefault("source", source)

    return articles[:max_items]


def _try_akshare(keywords: list[str], max_items: int) -> list[dict]:
    """尝试通过 AkShare 获取政策相关文章；任何异常返回空列表。"""
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol="全部")
        if df is None or df.empty:
            return []
        rows = []
        for _, row in df.head(max_items).iterrows():
            title = str(row.get("新闻标题", row.get("title", "")))
            content = str(row.get("新闻内容", row.get("content", "")))
            if not title:
                continue
            if keywords and not any(kw in title + content for kw in keywords):
                continue
            rows.append({
                "title": title,
                "content": content,
                "url": str(row.get("新闻链接", row.get("url", ""))),
                "published_at": str(row.get("发布时间", row.get("published_at", ""))),
                "source": "akshare_news",
                "content_hash": _hash_content(title, content),
            })
        return rows
    except Exception as e:
        print(f"[policy] AkShare 获取失败（降级到种子数据）: {e}")
        return []


def _load_seed() -> list[dict]:
    """加载本地种子政策数据。"""
    if not SEED_PATH.exists():
        return []
    try:
        with open(SEED_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[policy] 种子数据加载失败: {e}")
        return []


def ingest_policy_articles(conn, articles: list[dict]) -> dict:
    """幂等写入 policy_items，以 (source, content_hash) 唯一。

    Returns:
        {"inserted": int, "skipped": int}
    """
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    inserted = skipped = 0
    for a in articles:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO policy_items
                    (source, title, published_at, url, content, content_hash, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    a.get("source", "unknown"),
                    a.get("title", ""),
                    a.get("published_at", ""),
                    a.get("url", ""),
                    a.get("content", ""),
                    a.get("content_hash", _hash_content(a.get("title", ""), a.get("content", ""))),
                    now,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"[policy] ingest 失败: {e}")
    conn.commit()
    return {"inserted": inserted, "skipped": skipped}
