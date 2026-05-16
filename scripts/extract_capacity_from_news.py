#!/usr/bin/env python3
"""
从新闻自动提取产能数据，更新供需库
=====================================
扫描 news_items 表，提取产能/利用率/投产规划数据，
对比现有数据，自动更新 CAPACITY_DATABASE。

用法:
  python scripts/extract_capacity_from_news.py       # 扫描+打印差异
  python scripts/extract_capacity_from_news.py --dry   # 仅dry run，不写入
  python scripts/extract_capacity_from_news.py --save  # 写入到 supply_chain.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import re
import sqlite3
import json
from dataclasses import asdict
from datetime import datetime

from knowledge.supply_chain import CAPACITY_DATABASE, CapacityEntry


# ============================================================
# 公司名 → ticker 映射
# ============================================================
COMPANY_TICKER_MAP = {
    "中际旭创": "300308", "光迅科技": "002281", "新易盛": "300502",
    "博创科技": "300548", "天孚通信": "300394",
    "长电科技": "600584", "通富微电": "002156", "华天科技": "002185",
    "中芯国际": "688981", "华虹半导体": "688347",
    "沪硅产业": "688126", "有研硅": "688432", "中环股份": "002129", "立昂微": "605358",
    "北方华创": "002371", "中微公司": "688012", "拓荆科技": "688072", "华海清科": "688120",
    "三安光电": "600703", "源杰科技": "688498", "仕佳光子": "688313",
    "深南电路": "002916", "生益科技": "600183", "南亚新材": "688188",
    "寒武纪": "688256", "景嘉微": "300474", "韦尔股份": "603501",
    "卓胜微": "300782", "澜起科技": "688008", "华润微": "688396",
}

SEGMENT_MAP = {
    # 光模块
    "光模块": "光模块", "光通信": "光模块", "光器件": "光模块",
    "光模块": "光模块", "800G": "光模块", "1.6T": "光模块",
    # 封装
    "封装": "封装测试", "封测": "封装测试", "先进封装": "封装测试",
    "芯片封测": "封装测试", "封装测试": "封装测试",
    # 晶圆代工
    "晶圆": "晶圆代工", "代工": "晶圆代工", "芯片制造": "晶圆代工",
    # 硅片
    "硅片": "硅片/晶圆",
    # 半导体设备
    "刻蚀设备": "半导体设备", "CMP": "半导体设备", "PECVD": "半导体设备",
    "沉积设备": "半导体设备", "光刻机": "半导体设备",
    "半导体设备": "半导体设备", "设备": "半导体设备",
    # 光芯片
    "光芯片": "光芯片", "VCSEL": "光芯片", "DFB": "光芯片", "激光器": "光芯片",
    "磷化铟": "光芯片", "三五族": "光芯片",
    # PCB/载板
    "PCB": "PCB/载板", "载板": "PCB/载板", "覆铜板": "PCB/载板",
    "FC-BGA": "PCB/载板", "封装基板": "PCB/载板",
    # AI算力
    "算力": "AI算力", "服务器": "AI算力", "AI服务器": "AI算力",
}

# 精确公司→环节映射（防止错误分类）
COMPANY_SEGMENT_OVERRIDE = {
    "华海清科": "半导体设备",   # CMP设备，不是光芯片
    "北方华创": "半导体设备",
    "中微公司": "半导体设备",
    "拓荆科技": "半导体设备",
    "ASML": "半导体设备",
    "AMAT": "半导体设备",
    "三安光电": "光芯片",        # 芯片产能，不是封装
    "源杰科技": "光芯片",
    "仕佳光子": "光芯片",
    "长电科技": "封装测试",
    "通富微电": "封装测试",
    "华天科技": "封装测试",
    "中芯国际": "晶圆代工",
    "华虹半导体": "晶圆代工",
    "沪硅产业": "硅片/晶圆",
    "有研硅": "硅片/晶圆",
    "中环股份": "硅片/晶圆",
    "立昂微": "硅片/晶圆",
    "中际旭创": "光模块",
    "光迅科技": "光模块",
    "新易盛": "光模块",
    "博创科技": "光模块",
    "天孚通信": "光模块",
    "深南电路": "PCB/载板",
    "生益科技": "PCB/载板",
    "南亚新材": "PCB/载板",
}

UNIT_PATTERNS = [
    (r"(\d+(?:\.\d+)?)\s*万片/月", "万片/月"),
    (r"(\d+(?:\.\d+)?)\s*万颗/月", "万颗/月"),
    (r"(\d+(?:\.\d+)?)\s*万只/年", "万只/年"),
    (r"(\d+(?:\.\d+)?)\s*万片", "万片/月"),
    (r"(\d+(?:\.\d+)?)\s*万颗", "万颗/月"),
    (r"(\d+(?:\.\d+)?)\s*万只", "万只/年"),
    (r"(\d+(?:\.\d+)?)\s*万台/年", "万台/年"),
    (r"(\d+(?:\.\d+)?)\s*万平方米/年", "万平方米/年"),
    (r"(\d+(?:\.\d+)?)\s*台/年", "台/年"),
]

UTIL_PATTERNS = [
    (r"产能利用率[为是在]?\s*(\d+)%", "util"),
    (r"超过\s*(\d+)%", "util"),
    (r"约\s*(\d+)%", "util"),
    (r"(\d+)%", "util"),
]

DATE_PATTERNS = [
    (r"(\d{4})年(\d{1,2})月(?:提前)?投产", "ym"),
    (r"(\d{4})年(\d{1,2})季?投产", "yq"),
    (r"(\d{4})年(\d{1,2})月", "ym"),
    (r"(\d{4})年", "y"),
    (r"预计(\d{4})", "y"),
]

CAPACITY_AMOUNT_PATTERNS = [
    # 绝对产能
    r"(\d+(?:\.\d+)?)\s*万片/月",
    r"(\d+(?:\.\d+)?)\s*万颗/月",
    r"(\d+(?:\.\d+)?)\s*万只/年",
    r"(\d+(?:\.\d+)?)\s*万台/年",
    r"(\d+(?:\.\d+)?)\s*万平方米/年",
    # 投资额
    r"(\d+)\s*亿元",
    r"(\d+)\s*亿美元",
    # 百分数
    r"(\d+(?:\.\d+)?)\s*%",
]

# ============================================================
# 新闻产能提取
# ============================================================

def extract_capacity_from_news(conn) -> list[dict]:
    """扫描news_items，提取所有产能相关条目"""
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT title, content, published_at, source
        FROM news_items
        WHERE content IS NOT NULL AND content != '' AND content != 'nan' AND content != 'None'
        AND (
            content LIKE '%产能%' OR content LIKE '%投产%' OR content LIKE '%扩产%'
            OR content LIKE '%万片%' OR content LIKE '%万颗%' OR content LIKE '%万只%'
            OR content LIKE '%万片/月%' OR content LIKE '%万台%'
            OR content LIKE '%利用率%'
            OR title LIKE '%产能%' OR title LIKE '%投产%' OR title LIKE '%扩产%'
        )
        AND LENGTH(content) > 30
        ORDER BY published_at DESC
    """).fetchall()

    results = []
    for title, content, published_at, source in rows:
        text = f"{title} {content}"

        # 找公司名
        company_found = None
        for company in COMPANY_TICKER_MAP:
            if company in text:
                company_found = company
                break

        if not company_found:
            continue

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
                if pattern.startswith(r"(\d+)"):
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

        # 判断是在建还是已投产
        status = "在产"
        if any(kw in text for kw in ["在建", "规划中", "建设中", "扩产", "将建成", "将新增"]):
            status = "在建"
        if any(kw in text for kw in ["量产", "批量", "已投产", "已量产", "已批量"]):
            status = "在产"
        if any(kw in text for kw in ["产能不足", "供不应求", "产能紧张"]):
            status = "在产"  # 已有产能供不应求

        # 判断产品/环节 - 优先用公司→环节映射，再泛化匹配
        segment = None
        if company_found in COMPANY_SEGMENT_OVERRIDE:
            segment = COMPANY_SEGMENT_OVERRIDE[company_found]
        else:
            for kw, seg in SEGMENT_MAP.items():
                if kw in text:
                    segment = seg
                    break

        if capacity_value or utilization:
            results.append({
                "company": company_found,
                "ticker": COMPANY_TICKER_MAP.get(company_found, ""),
                "title": title,
                "published_at": published_at,
                "segment": segment,
                "capacity_value": capacity_value,
                "capacity_unit": capacity_unit,
                "utilization": utilization,
                "invest_amount": invest_amount,
                "production_date": production_date,
                "status": status,
                "text_snippet": text[:200],
            })

    return results


def merge_with_existing(extracted: list[dict]) -> list[CapacityEntry]:
    """
    将提取的产能数据与现有 CAPACITY_DATABASE 合并
    规则:
      - 新数据比现有新的，用新数据替换
      - 同公司同环节，取最新的记录
      - 保留所有现有数据，只更新+新增
    """
    # 按 (company, segment) 索引现有数据
    existing = {}
    for e in CAPACITY_DATABASE:
        key = (e.company, e.segment)
        existing[key] = e

    # 合并
    updated_keys = set()
    for ex in extracted:
        key = (ex["company"], ex.get("segment", ""))
        if not ex.get("segment"):
            continue

        if key in existing:
            # 更新现有条目
            e = existing[key]
            if ex["capacity_value"] and ex["capacity_unit"] == e.capacity_unit:
                e.capacity_current = ex["capacity_value"]
                e.utilization = ex["utilization"] or e.utilization
            if ex["production_date"]:
                e.production_date = ex["production_date"]
            if ex["status"] in ("在产", "在建"):
                e.status = ex["status"]
            e.notes = f"[{ex['published_at'][:10]}] {ex['title'][:80]}"
            updated_keys.add(key)
        else:
            # 新增
            new_entry = CapacityEntry(
                company=ex["company"],
                ticker=ex["ticker"],
                segment=ex["segment"],
                product=ex["segment"],
                capacity_current=ex["capacity_value"] or 0,
                capacity_unit=ex["capacity_unit"] or "万片/月",
                utilization=ex["utilization"] or 0.80,
                capacity_building=0,
                production_date=ex["production_date"],
                status=ex["status"],
                notes=f"[{ex['published_at'][:10]}] {ex['title'][:80]}",
            )
            existing[key] = new_entry
            updated_keys.add(key)

    return list(existing.values())


def print_extraction_report(extracted: list[dict], existing: list[CapacityEntry]):
    """打印提取报告"""
    print("=" * 70)
    print(f"📰 新闻产能数据提取报告 ({len(extracted)}条)")
    print("=" * 70)

    # 按公司分组
    by_company = {}
    for ex in extracted:
        c = ex["company"]
        if c not in by_company:
            by_company[c] = []
        by_company[c].append(ex)

    for company, items in by_company.items():
        ticker = items[0]["ticker"]
        print(f"\n【{company}】({ticker})")
        for it in items:
            seg = it.get("segment", "未知")
            cap = f"{it['capacity_value']}{it['capacity_unit']}" if it["capacity_value"] else "?"
            util = f"{it['utilization']*100:.0f}%" if it["utilization"] else "?"
            pd = it["production_date"] or "?"
            status = it["status"]
            print(f"  {seg:<10} 产能:{cap:<15} 利用率:{util:<8} 投产:{pd:<8} [{status}]")
            print(f"    📌 {it['title'][:60]}")

    print("\n" + "=" * 70)
    print(f"📊 合并后产能库: {len(existing)} 条记录")
    print("=" * 70)


def generate_supply_chain_py(entries: list[CapacityEntry], path: str):
    """将CapacityEntry列表生成 supply_chain_data.py 文件"""
    lines = ['"""', '"""']
    # 这里只是保存提取的数据为JSON/SQLite，下一步再做


def save_to_db(extracted: list[dict], conn: sqlite3.Connection):
    """将提取的产能数据写入SQLite"""
    cur = conn.cursor()
    saved = 0
    for ex in extracted:
        if not ex.get("segment") or ex["segment"] == "未知":
            continue
        try:
            cur.execute("""
                INSERT INTO capacity_data
                (company, ticker, segment, product, capacity_current, capacity_unit,
                 utilization, capacity_building, production_date, status, notes, source)
                VALUES (:company, :ticker, :segment, :product, :cap, :unit,
                 :util, 0, :prod_date, :status, :notes, :src)
                ON CONFLICT(company, segment) DO UPDATE SET
                    capacity_current = COALESCE(excluded.capacity_current, capacity_current),
                    utilization = COALESCE(excluded.utilization, utilization),
                    production_date = COALESCE(excluded.production_date, production_date),
                    status = COALESCE(excluded.status, status),
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
            """, {
                "company": ex["company"], "ticker": ex["ticker"],
                "segment": ex["segment"], "product": ex["segment"],
                "cap": ex["capacity_value"], "unit": ex["capacity_unit"],
                "util": ex["utilization"],
                "prod_date": ex["production_date"], "status": ex["status"],
                "notes": f"[{ex['published_at'][:10]}] {ex['title'][:100]}",
                "src": str(ex.get("source", "")),
            })
            saved += 1
        except Exception as e:
            print(f"  ⚠️ 写入失败 {ex['company']}: {e}")
    conn.commit()
    return saved


def load_from_db(conn: sqlite3.Connection) -> list[CapacityEntry]:
    """从SQLite加载动态产能数据"""
    cur = conn.cursor()
    rows = cur.execute("SELECT company, ticker, segment, product, capacity_current, capacity_unit, utilization, capacity_building, production_date, status, notes FROM capacity_data").fetchall()
    entries = []
    for r in rows:
        entries.append(CapacityEntry(
            company=r[0], ticker=r[1] or "", segment=r[2], product=r[3] or r[2],
            capacity_current=r[4] or 0, capacity_unit=r[5] or "万片/月",
            utilization=r[6] or 0.80, capacity_building=r[7] or 0,
            production_date=r[8], status=r[9] or "在产", notes=r[10] or ""
        ))
    return entries


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="仅打印，不写入")
    parser.add_argument("--save", action="store_true", help="写入数据库")
    args = parser.parse_args()

    conn = sqlite3.connect("data/cache/quant_data.db")

    if args.save:
        extracted = extract_capacity_from_news(conn)
        saved = save_to_db(extracted, conn)
        print(f"✅ 写入 {saved} 条到数据库")
    else:
        extracted = extract_capacity_from_news(conn)
        print(f"从新闻中提取到 {len(extracted)} 条产能数据\n")
        for ex in extracted:
            util_str = f"{ex['utilization']*100:.0f}%" if ex['utilization'] else "?"
            cap_str = f"{ex['capacity_value']}{ex['capacity_unit']}" if ex['capacity_value'] else "?"
            print(f"  {ex['company']}({ex['ticker']}) | {ex.get('segment','?')} | "
                  f"产能:{cap_str} | 利用率:{util_str} | "
                  f"状态:{ex['status']} | {ex['published_at'][:10]}")
            print(f"    📌 {ex['title'][:70]}")

    # 演示从数据库读取
    print("\n📊 数据库中的动态产能数据:")
    db_entries = load_from_db(conn)
    for e in db_entries:
        print(f"  {e.company}({e.ticker}) | {e.segment} | {e.capacity_current}{e.capacity_unit} | 利用率:{e.utilization*100:.0f}%")

    conn.close()
