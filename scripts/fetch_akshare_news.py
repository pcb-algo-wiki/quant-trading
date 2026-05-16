#!/usr/bin/env python3
"""
批量抓取akshare个股新闻 → news_items表 + 产能提取
==================================================
对 stock_pool 里所有A股 ticker 抓取最新10条新闻，
写入 news_items 表（供知识图谱用）+ 同步提取产能数据到 capacity_data。

用法:
  python scripts/fetch_akshare_news.py          # 增量抓取（跳过已有）
  python scripts/fetch_akshare_news.py --full  # 全量重抓（慎用）
  python scripts/fetch_akshare_news.py --test  # 仅测试3只股票
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
import sqlite3
import re
import hashlib
from datetime import datetime

import akshare as ak

from data.stock_pool import ALL_STOCKS
from scripts.extract_capacity_from_news import (
    COMPANY_TICKER_MAP, COMPANY_SEGMENT_OVERRIDE, SEGMENT_MAP,
    UNIT_PATTERNS, DATE_PATTERNS, extract_capacity_from_news,
)


def get_db():
    return sqlite3.connect("data/cache/quant_data.db")


def ticker_exists(conn, title: str, published_at: str) -> bool:
    """检查新闻是否已存在（去重）"""
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM news_items WHERE title = ? AND published_at = ?", (title, published_at)
    ).fetchone()
    return row is not None


def insert_news(conn, row: dict):
    """写入 news_items 表"""
    cur = conn.cursor()
    # 先去重
    if ticker_exists(conn, row["title"], row["published_at"]):
        return False
    try:
        cur.execute("""
            INSERT INTO news_items (title, content, source, published_at, url, tags)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            row["title"], row["content"], row.get("source", "akshare"),
            row["published_at"], row.get("url", ""), row.get("tags", ""),
        ))
        return True
    except Exception:
        return False


def extract_capacity_from_text(text: str, company: str, title: str, published_at: str) -> dict | None:
    """从单条新闻文本提取产能数据"""
    # 找公司名
    company_found = None
    for c in COMPANY_TICKER_MAP:
        if c in text:
            company_found = c
            break
    if not company_found:
        return None

    # 提取产能数字
    capacity_value = None
    capacity_unit = None
    for pattern, unit in UNIT_PATTERNS:
        m = re.search(pattern, text)
        if m:
            capacity_value = float(m.group(1))
            capacity_unit = unit
            break

    # 提取产能利用率
    utilization = None
    util_matches = re.findall(r"(\d+)%", text)
    for um in util_matches:
        v = int(um)
        if 30 <= v <= 110:
            utilization = v / 100
            break

    # 提取投资额
    invest_amount = None
    for pattern in [r"(\d+)\s*亿元", r"(\d+)\s*亿美元"]:
        m = re.search(pattern, text)
        if m:
            val = float(m.group(1))
            invest_amount = val
            break

    # 提取投产时间
    production_date = None
    for pattern, fmt in DATE_PATTERNS:
        m = re.search(pattern, text)
        if m:
            if fmt == "ym":
                y, mo = int(m.group(1)), int(m.group(2))
                q = (mo - 1) // 3 + 1
                production_date = f"{y}Q{q}"
            elif fmt == "yq":
                y, q = int(m.group(1)), int(m.group(2))
                production_date = f"{y}Q{q}"
            elif fmt == "y":
                production_date = f"{int(m.group(1))}Q1"
            break

    # 判断状态
    status = "在产"
    if any(kw in text for kw in ["在建", "规划中", "建设中", "扩产", "将建成", "将新增"]):
        status = "在建"
    if any(kw in text for kw in ["量产", "批量", "已投产", "已量产", "已批量"]):
        status = "在产"
    if any(kw in text for kw in ["产能不足", "供不应求", "产能紧张"]):
        status = "在产"

    # 判断环节
    segment = None
    if company_found in COMPANY_SEGMENT_OVERRIDE:
        segment = COMPANY_SEGMENT_OVERRIDE[company_found]
    else:
        for kw, seg in SEGMENT_MAP.items():
            if kw in text:
                segment = seg
                break

    if capacity_value or utilization:
        return {
            "company": company_found,
            "ticker": COMPANY_TICKER_MAP.get(company_found, ""),
            "segment": segment,
            "capacity_value": capacity_value,
            "capacity_unit": capacity_unit,
            "utilization": utilization,
            "invest_amount": invest_amount,
            "production_date": production_date,
            "status": status,
            "news_title": title,
            "news_url": "",
            "source": "akshare",
            "tags": "",
            "published_at": published_at,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    return None


def ensure_tables(conn):
    """确保 capacity_data 表存在且 schema 完整"""
    cur = conn.cursor()
    # 先检查现有列
    cur.execute("PRAGMA table_info(capacity_data)")
    existing_cols = {row[1] for row in cur.fetchall()}

    # 确保有基础列
    required = {
        "id", "company", "ticker", "segment", "product",
        "capacity_current", "capacity_unit", "utilization",
        "capacity_building", "capacity_building_unit", "capex",
        "production_date", "growth_rate", "supply_demand_delta",
        "news_title", "news_url", "updated_at", "source", "tags",
    }
    missing = required - existing_cols
    if missing:
        for col in missing:
            try:
                cur.execute(f"ALTER TABLE capacity_data ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # 已存在

    # 如果表不存在则创建完整 schema
    cur.execute("""
        CREATE TABLE IF NOT EXISTS capacity_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT,
            ticker TEXT,
            segment TEXT,
            product TEXT,
            capacity_current REAL,
            capacity_unit TEXT,
            utilization REAL,
            capacity_building REAL,
            capacity_building_unit TEXT,
            capex REAL,
            production_date TEXT,
            growth_rate REAL,
            supply_demand_delta REAL,
            news_title TEXT,
            news_url TEXT,
            updated_at TEXT,
            source TEXT,
            tags TEXT
        )
    """)


def capacity_exists(conn, company: str, segment: str) -> dict | None:
    """查同company+segment是否已有记录"""
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM capacity_data WHERE company=? AND segment=? LIMIT 1",
        (company, segment)
    ).fetchone()
    if row:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return None


def upsert_capacity(conn, cap: dict):
    """upsert一条产能数据"""
    existing = capacity_exists(conn, cap["company"], cap["segment"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existing:
        # 更新
        cur = conn.cursor()
        cur.execute("""
            UPDATE capacity_data SET
                capacity_current = COALESCE(?, capacity_current),
                utilization = COALESCE(?, utilization),
                production_date = COALESCE(?, production_date),
                news_title = ?,
                updated_at = ?
            WHERE company = ? AND segment = ?
        """, (
            cap.get("capacity_value") or existing.get("capacity_current"),
            cap.get("utilization") or existing.get("utilization"),
            cap.get("production_date") or existing.get("production_date"),
            cap.get("news_title", ""),
            now,
            cap["company"], cap["segment"],
        ))
    else:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO capacity_data
                (company, ticker, segment, product, capacity_current, capacity_unit,
                 utilization, capacity_building, production_date, news_title,
                 updated_at, source, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cap["company"],
            cap.get("ticker", ""),
            cap.get("segment", ""),
            cap.get("segment", ""),
            cap.get("capacity_value") or 0,
            cap.get("capacity_unit", "万片/月"),
            cap.get("utilization") or 0.80,
            0,
            cap.get("production_date"),
            cap.get("news_title", ""),
            now,
            cap.get("source", "akshare"),
            cap.get("tags", ""),
        ))


def fetch_news_for_ticker(ticker: str, market: str = "A股") -> list[dict]:
    """抓取单只股票的akshare新闻"""
    try:
        df = ak.stock_news_em(symbol=ticker)
        results = []
        for _, row in df.iterrows():
            content = str(row.get("新闻内容", ""))
            title = str(row.get("新闻标题", ""))
            published_at = str(row.get("发布时间", ""))
            source = str(row.get("文章来源", "akshare"))
            url = str(row.get("新闻链接", ""))
            if not title or title == "nan":
                continue
            results.append({
                "title": title,
                "content": content,
                "published_at": published_at,
                "source": source,
                "url": url,
                "tags": ticker,
            })
        return results
    except Exception as e:
        return []


def run(full: bool = False, test: bool = False):
    conn = get_db()
    ensure_tables(conn)

    # 构建 ticker 列表
    if test:
        tickers = [("300308", "SZ"), ("688017", "SH"), ("300124", "SZ")]
    else:
        tickers = []
        seen = set()
        for ticker, info in ALL_STOCKS.items():
            if ticker not in seen:
                seen.add(ticker)
                market = info[0]  # "SH" or "SZ"
                tickers.append((ticker, market))

    total_news = 0
    total_capacity = 0
    errors = []

    for i, (ticker, market) in enumerate(tickers):
        if i % 20 == 0:
            print(f"[{i}/{len(tickers)}] 进度...")

        news_list = fetch_news_for_ticker(ticker, market)
        for news in news_list:
            inserted = insert_news(conn, news)
            if inserted:
                total_news += 1

            # 尝试提取产能数据
            text = f"{news['title']} {news['content']}"
            cap = extract_capacity_from_text(text, "", news["title"], news["published_at"])
            if cap and cap.get("segment"):
                upsert_capacity(conn, cap)
                total_capacity += 1

        time.sleep(0.25)  # 礼貌限速

    conn.commit()
    conn.close()

    print(f"\n✅ 完成: 写入{total_news}条新闻, 提取{total_capacity}条产能数据")

    if errors:
        print(f"⚠️ 出错({len(errors)}次): {errors[:5]}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="全量重抓")
    parser.add_argument("--test", action="store_true", help="仅测试3只股票")
    args = parser.parse_args()

    run(full=args.full, test=args.test)
