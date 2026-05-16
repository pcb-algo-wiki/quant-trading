#!/usr/bin/env python3
"""
个股走势与供需周期对照分析
============================
用法:
  python scripts/analyze_supply_demand.py              # 全产业链分析
  python scripts/analyze_supply_demand.py 光模块       # 单环节分析
  python scripts/analyze_supply_demand.py --stock 300308  # 单个股股详细分析
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import sqlite3
from datetime import date, timedelta
from typing import Optional

# 供需数据库
from knowledge.supply_chain import (
    CAPACITY_DATABASE, CYCLE_PHASES, CYCLE_PHASES,
    get_supply_demand_gap, get_stock_by_segment, get_segment_capacity,
    SEMI_CHAIN_SEGMENTS, OPTICAL_CHAIN_SEGMENTS, CapacityEntry
)
from scripts.extract_capacity_from_news import load_from_db

# 个股走势数据
from data.stock_pool import ALL_STOCKS
from data.yahoo_us import fetch_us_etf
from data.stock_fetcher import fetch_stock_cached
import sqlite3


# ──────────────────────────────────────────────────────────
# 供需缺口时间轴
# ──────────────────────────────────────────────────────────

def get_cycle_phase_at(segment: str, ref_date: str) -> Optional[dict]:
    """
    给定环节和时间，返回当时所处周期阶段
    ref_date格式: "2024-01-15" 或 "2024Q1"
    """
    # 解析时间
    if "Q" in ref_date:
        year, q = ref_date.split("Q")
        month_map = {"1": "01", "2": "04", "3": "07", "4": "10"}
        ref_month = int(month_map[q])
        ref_dt = f"{year}-{ref_month}-01"
    else:
        ref_dt = ref_date

    for phase in CYCLE_PHASES:
        if phase.segment != segment:
            continue
        start = phase.start_period
        end = phase.end_period or "2030Q4"

        # 解析 start/end 到 (year, quarter)
        def to_yq(s):
            if "Q" in s:
                y, q = s.split("Q")
                return int(y), int(q)
            return 9999, 99

        sy, sq = to_yq(start)
        ey, eq = to_yq(end)
        ry, rq = to_yq(ref_date)

        # 简单比较
        if (ry, rq) >= (sy, sq) and (ry, rq) <= (ey, eq):
            return {
                "phase": phase.phase,
                "gap_ratio": phase.gap_ratio,
                "price_trend": phase.price_trend,
                "start": start,
                "end": end,
            }
    return None


def print_cycle_history(segment: str):
    """打印某环节历史周期阶段"""
    print(f"\n{'=' * 60}")
    print(f"📅 {segment} 供需周期历史")
    print(f"{'=' * 60}")
    for phase in CYCLE_PHASES:
        if phase.segment != segment:
            continue
        icon = "🔴" if phase.phase == "紧缺" else ("🔵" if phase.phase == "过剩" else ("🟡" if phase.phase == "去化" else "⚪"))
        gap_str = f"+{phase.gap_ratio*100:.0f}%" if phase.gap_ratio > 0 else f"{phase.gap_ratio*100:.0f}%"
        end_str = phase.end_period or "至今"
        print(f"  {icon} [{phase.start_period} → {end_str}] {phase.phase}  供需缺口:{gap_str}  价格:{phase.price_trend}")


def get_price_period_return(ticker: str, start_date: str, end_date: str) -> Optional[dict]:
    """计算某时间段股价涨跌（A股用新浪，美股用yfinance）"""
    try:
        if ticker.isdigit() and len(ticker) == 6:
            # A股: 用stock_fetcher
            market = "SH" if ticker.startswith(("6", "5")) else "SZ"
            df = fetch_stock_cached(ticker, market, max_days=2000)
            if df is None or len(df) < 2:
                return None
            df["date"] = df["date"].astype(str)
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            df_sub = df[mask]
            if len(df_sub) < 2:
                return None
            start_p = df_sub.iloc[0]["close"]
            end_p = df_sub.iloc[-1]["close"]
            ret = (end_p / start_p - 1) * 100
            return {"start_price": float(start_p), "end_price": float(end_p), "return_pct": ret, "days": len(df_sub)}
        else:
            # 美股/ETF: 用yfinance
            df = fetch_us_etf(ticker, start=start_date, end=end_date)
            if df is None or len(df) < 2:
                return None
            start_p = df.iloc[0]["close"]
            end_p = df.iloc[-1]["close"]
            ret = (end_p / start_p - 1) * 100
            return {"start_price": float(start_p), "end_price": float(end_p), "return_pct": ret, "days": len(df)}
    except Exception as e:
        return None


def analyze_segment_stocks(segment: str):
    """分析某环节所有个股在周期各阶段的走势"""
    stocks = get_stock_by_segment(segment)
    if not stocks:
        print(f"  (无对应股票数据)")
        return

    # 按年份分析
    years = ["2021", "2022", "2023", "2024", "2025"]

    print(f"\n{'─' * 60}")
    print(f"📈 {segment} 个股在供需周期各阶段的走势")
    print(f"{'─' * 60}")
    print(f"{'公司':<12} {'时段':<10} {'周期':<6} {'缺口':<8} {'价格涨跌':<12} {'说明'}")
    print(f"{'─' * 60}")

    for ticker, name in stocks:
        for year in years:
            h1 = f"{year}Q1"
            h2 = f"{year}Q2"
            full = f"{year}"

            for period in [h1, h2, full]:
                # 判断周期阶段
                ph = get_cycle_phase_at(segment, period)
                if not ph:
                    continue

                # 估算时间段
                if "Q1" in period:
                    s, e = f"{year}-01-01", f"{year}-04-01"
                elif "Q2" in period:
                    s, e = f"{year}-04-01", f"{year}-07-01"
                else:
                    s, e = f"{year}-01-01", f"{year+1}-01-01" if year != "2025" else f"{year}-12-31"

                ret = get_price_period_return(ticker, s, e)

                icon = "🔴" if ph["phase"] == "紧缺" else ("🔵" if ph["phase"] == "过剩" else "⚪")
                if ret:
                    ret_str = f"{ret['return_pct']:+.1f}%"
                    price_str = f"¥{ret['start_price']:.1f}→¥{ret['end_price']:.1f}"
                else:
                    ret_str = "N/A"
                    price_str = ""

                print(f"  {name:<10} {period:<10} {icon}{ph['phase']:<5} {ph['gap_ratio']*100:>+6.0f}%  {ret_str:<12} {price_str}")


# ──────────────────────────────────────────────────────────
# 供需缺口未来预警
# ──────────────────────────────────────────────────────────

def get_all_capacity() -> list:
    """合并: 静态供需库(基础数据) + 动态新闻提取(实时更新)"""
    static = {f"{e.company}|{e.segment}": e for e in CAPACITY_DATABASE}
    try:
        conn = sqlite3.connect("data/cache/quant_data.db")
        db_entries = load_from_db(conn)
        conn.close()
        for e in db_entries:
            key = f"{e.company}|{e.segment}"
            if key in static:
                s = static[key]
                if e.capacity_current > 0:
                    s.capacity_current = e.capacity_current
                if e.utilization and e.utilization > 0:
                    s.utilization = e.utilization
                if e.production_date:
                    s.production_date = e.production_date
                s.notes = e.notes
            else:
                static[key] = e
    except Exception:
        pass
    return list(static.values())


def get_segment_capacity_dynamic(segment: str) -> tuple[float, float, float]:
    """返回: (当前产能总计, 在建产能总计, 产能利用率) — 动态合并数据"""
    all_cap = get_all_capacity()
    entries = [e for e in all_cap if e.segment == segment]
    if not entries:
        return 0, 0, 0
    current = sum(e.capacity_current * e.utilization for e in entries)
    building = sum(e.capacity_building for e in entries)
    avg_util = sum(e.utilization for e in entries) / len(entries)
    return current, building, avg_util


def get_supply_demand_gap_dynamic(segment: str, months_ahead: int = 0) -> dict:
    """带动态数据更新的供需缺口计算"""
    all_cap = get_all_capacity()
    entries = [e for e in all_cap if e.segment == segment]
    if not entries:
        return {"segment": segment, "supply": 0, "demand": 0, "gap": 0, "gap_pct": 0, "status": "均衡", "months_ahead": months_ahead}

    current = sum(e.capacity_current * e.utilization for e in entries)
    building = sum(e.capacity_building for e in entries)
    if months_ahead == 0:
        supply = current
    else:
        supply = current + building * min(months_ahead / 18, 1.0)

    phases = [p for p in CYCLE_PHASES if p.segment == segment and p.end_period is None]
    if phases:
        gap_ratio = phases[-1].gap_ratio
    else:
        gap_ratio = 0

    demand = supply / (1 + gap_ratio) if gap_ratio > -0.99 else supply * 1.2
    gap = supply - demand
    gap_pct = gap / demand * 100 if demand > 0 else 0

    return {
        "segment": segment,
        "supply": round(supply, 2),
        "demand": round(demand, 2),
        "gap": round(gap, 2),
        "gap_pct": round(gap_pct, 1),
        "status": "紧缺" if gap > 0 else ("过剩" if gap < -supply * 0.05 else "均衡"),
        "months_ahead": months_ahead,
    }


def print_supply_alert():
    """打印未来3/6/9/12个月供需缺口预警 — 使用动态数据"""
    all_segs = list(set(e.segment for e in get_all_capacity()))

    print(f"\n{'=' * 70}")
    print(f"⚠️  供需缺口预警 (供给 - 需求) [新闻实时更新]")
    print(f"{'=' * 70}")
    print(f"{'环节':<14} {'当前':<10} {'3个月':<10} {'6个月':<10} {'9个月':<10} {'12个月':<10} {'趋势'}")
    print(f"{'─' * 70}")

    for seg in all_segs:
        rows = []
        for months in [0, 3, 6, 9, 12]:
            gap = get_supply_demand_gap_dynamic(seg, months)
            rows.append(gap)

        gaps = [r["gap_pct"] for r in rows]
        if gaps[-1] > gaps[0] + 5:
            trend = "🔴 缺口扩大"
        elif gaps[-1] < gaps[0] - 5:
            trend = "🟢 缺口收敛"
        else:
            trend = "🟡 基本持平"

        def fmt(r):
            icon = "🔴" if r["status"] == "紧缺" else ("🟢" if r["status"] == "均衡" else "🔵")
            return f"{icon}{r['gap_pct']:>+.0f}%"

        print(f"  {seg:<12} {fmt(rows[0]):<10} {fmt(rows[1]):<10} {fmt(rows[2]):<10} {fmt(rows[3]):<10} {fmt(rows[4]):<10} {trend}")


# ──────────────────────────────────────────────────────────
# 产能投产时间线
# ──────────────────────────────────────────────────────────

def print_capacity_timeline():
    """打印未来1年内新产能投产时间线"""
    all_cap = get_all_capacity()
    building = [e for e in all_cap if e.capacity_building > 0]

    print(f"\n{'=' * 70}")
    print(f"🏗️  未来1年新产能投产时间线")
    print(f"{'─' * 70}")

    def sort_key(e):
        pd = e.production_date or "2030Q1"
        y, q = pd.split("Q")
        return (int(y), int(q))

    building.sort(key=sort_key)

    print(f"{'公司':<10} {'环节':<12} {'产品':<16} {'新产能':<12} {'预计投产':<10} {'缺口状态'}")
    print(f"{'─' * 70}")
    for e in building:
        gap = get_supply_demand_gap_dynamic(e.segment, 0)
        icon = "🔴" if gap["status"] == "紧缺" else ("🟢" if gap["status"] == "均衡" else "🔵")
        print(f"  {e.company:<8} {e.segment:<12} {e.product:<16} {e.capacity_building}{e.capacity_unit:<10} {e.production_date or '?':<10} {icon}{gap['gap_pct']:+.0f}%")


# ──────────────────────────────────────────────────────────
# 主报告
# ──────────────────────────────────────────────────────────

def generate_full_report():
    """生成完整供需分析报告 — 动态数据版"""
    all_segs = list(set(e.segment for e in get_all_capacity()))

    print("=" * 70)
    print("📊 半导体+光通信 供需产业链全景分析")
    print("=" * 70)

    print_supply_alert()
    print_capacity_timeline()

    for seg in all_segs:
        print_cycle_history(seg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("segment", nargs="?", default=None, help="指定环节，如'光模块'")
    parser.add_argument("--stock", default=None, help="指定个股代码")
    parser.add_argument("--alert", action="store_true", help="只看供需预警")
    args = parser.parse_args()

    if args.alert:
        print_supply_alert()
    elif args.segment:
        print_cycle_history(args.segment)
        analyze_segment_stocks(args.segment)
        gap = get_supply_demand_gap(args.segment, 0)
        print(f"\n当前供需: {gap}")
    elif args.stock:
        # 单个股详细分析
        print(f"个股 {args.stock} 供需周期分析")
    else:
        generate_full_report()
