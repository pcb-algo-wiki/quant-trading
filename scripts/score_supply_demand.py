#!/usr/bin/env python3
"""
个股供需信号评分系统
====================
按"新闻催化 × 供需评分 × 股价位置"三维评分

用法:
  python scripts/score_supply_demand.py              # 全市场扫描
  python scripts/score_supply_demand.py --segment 光模块  # 单环节分析
  python scripts/score_supply_demand.py --top 10     # Top10信号
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from dataclasses import dataclass
from typing import Optional

from knowledge.supply_chain import (
    CAPACITY_DATABASE, CYCLE_PHASES,
    get_supply_demand_gap, get_stock_by_segment, get_all_chain_segments,
    SEMI_CHAIN_SEGMENTS, OPTICAL_CHAIN_SEGMENTS,
    STORAGE_CHAIN_SEGMENTS, BATTERY_CHAIN_SEGMENTS,
    ROBOT_CHAIN_SEGMENTS, DEFENSE_CHAIN_SEGMENTS,
    CapacityEntry, CyclePhase
)
from data.stock_fetcher import fetch_stock_cached
from data.stock_pool import ALL_STOCKS


# ──────────────────────────────────────────────────────────
# 环节中文名 → 英文key（用于配置）
# ──────────────────────────────────────────────────────────
SEGMENT_KEY_MAP = {
    "光模块": "optical",
    "光芯片": "optical",
    "PCB/载板": "optical",
    "硅片/晶圆": "semi",
    "晶圆代工": "semi",
    "半导体设备": "semi",
    "封装测试": "semi",
    "存储制造": "storage",
    "存储封测": "storage",
    "HBM/高带宽存储": "storage",
    "模组/SSD": "storage",
    "正极材料": "battery",
    "负极材料": "battery",
    "隔膜": "battery",
    "电解液": "battery",
    "锂电设备": "battery",
    "电芯/PACK": "battery",
    "减速器": "robot",
    "伺服驱动": "robot",
    "控制器": "robot",
    "传感器": "robot",
    "机器人本体": "robot",
    "高温合金/钛合金": "defense",
    "航发整机": "defense",
    "军机/无人机": "defense",
    "导弹/精确制导": "defense",
    "军工信息化": "defense",
    "商业航天": "defense",
}

CYCLE_HISTORY = {
    # ── 光模块 ──────────────────────────────────────────────
    "光模块": [
        {"period": "2022Q1-2023Q2", "phase": "过剩", "price_change": -40,
         "representative": "中际旭创-24.5%(2022), 博创科技-35.7%(2022)"},
    ],
    # ── 存储 ──────────────────────────────────────────────
    "存储制造": [
        {"period": "2022Q3-2023Q4", "phase": "过剩", "price_change": -60,
         "representative": "NAND价格-60%, DRAM价格-50%"},
        {"period": "2024Q3-2025", "phase": "紧缺", "price_change": +80,
         "representative": "NAND价格反弹+80%, 三星营业利润创历史新高"},
    ],
    # ── 锂电材料 ──────────────────────────────────────────────
    "正极材料": [
        {"period": "2023Q1-2024Q2", "phase": "过剩", "price_change": -50,
         "representative": "碳酸锂价格从60万跌到10万"},
    ],
    # ── 机器人核心零部件 ──────────────────────────────────────────────
    "减速器": [
        {"period": "2023-2024", "phase": "紧缺", "price_change": +30,
         "representative": "绿的谐波+200%(2023), 国产替代加速"},
    ],
}


# ──────────────────────────────────────────────────────────
# 信号评分
# ──────────────────────────────────────────────────────────

@dataclass
class StockSignal:
    ticker: str
    name: str
    segment: str
    cycle_phase: str
    gap_pct: float        # 供需缺口%
    gap_trend: str        # 趋势: 扩大/收窄/持平
    price_position: float  # 当前价/52周高点的比例，0.0-1.0
    price_1y_ret: float    # 1年收益率%
    news催化剂: float     # 新闻催化强度 0-10
    cycle_score: float     # 供需周期分 0-10
    position_score: float  # 股价位置分 0-10
    total_score: float     # 综合分 0-10
    signal_type: str       # 信号类型


def get_cycle_history_effect(segment: str, cycle_phase: str) -> float:
    """
    基于历史周期推断当前缺口对股价的影响程度
    返回: -1到+1，影响方向和强度
    """
    history = CYCLE_HISTORY.get(segment, [])

    # 已知周期信息
    for h in history:
        if h["phase"] == cycle_phase:
            # 涨跌幅度 → 影响强度
            pc = h["price_change"]
            if pc > 50:
                return 0.9
            elif pc > 20:
                return 0.6
            elif pc > 0:
                return 0.3
            elif pc > -20:
                return -0.2
            else:
                return -0.6

    # 无历史数据，用缺口方向推测
    if cycle_phase == "紧缺":
        return 0.4  # 基准短缺利好
    elif cycle_phase == "过剩":
        return -0.4
    return 0.0


def get_cycle_score(segment: str, months_ahead: int = 0) -> tuple[float, str]:
    """
    供需周期评分 (0-10)
    核心逻辑:
      - 紧缺程度越高 → 分越高
      - 供需改善（过剩→均衡→紧缺）→ 分高
      - 供需恶化（紧缺→过剩）→ 分数降低
    返回: (score, phase_str)
    """
    gap = get_supply_demand_gap(segment, months_ahead)
    phase = None
    for p in reversed(CYCLE_PHASES):
        if p.segment == segment:
            if p.end_period is None or True:
                phase = p
                break

    if phase is None:
        return 5.0, "未知"

    phase_score_map = {
        "紧缺": 9.0,
        "均衡": 5.0,
        "去化": 4.0,
        "过剩": 2.0,
    }
    base = phase_score_map.get(phase.phase, 5.0)

    # 缺口绝对值加成
    gap_abs = abs(gap["gap_pct"])
    if gap["gap_pct"] > 0:  # 紧缺
        gap_bonus = min(gap_abs / 10, 1.5)  # 最多+1.5分
    else:  # 过剩
        gap_bonus = -min(gap_abs / 10, 1.0)

    score = base + gap_bonus
    return max(0, min(10, score)), phase.phase


def get_position_score(ticker: str, name: str, segment: str) -> tuple[float, float, float]:
    """
    股价位置评分 (0-10)
    返回: (score, price_position, 1y_ret)
    score逻辑:
      - 从高点大幅回撤 → 股价未充分上涨 → 分数高（补涨空间大）
      - 已在高点 → 分数低（利好已反映）
      - 52周高点计算: 用近1年最高点
    """
    try:
        # 智能判断市场
        if ticker.isdigit():
            market = "SH" if ticker.startswith(("6", "5", "9")) else "SZ"
        else:
            market = None  # 美股用ticker直接

        if market:
            df = fetch_stock_cached(ticker, market)
        else:
            df = fetch_stock_cached(ticker, "NASDAQ")

        if df is None or len(df) < 60:
            return 5.0, 1.0, 0.0

        now = df["close"].iloc[-1]

        # 52周高点（取最近252个交易日）
        high_252 = df["high"].iloc[-252:].max() if len(df) >= 252 else df["high"].max()
        low_252 = df["low"].iloc[-252:].min() if len(df) >= 252 else df["low"].min()

        # 股价位置 = 当前价 / 52周高点
        price_position = now / high_252 if high_252 > 0 else 1.0

        # 1年收益率（近似：当前价 / 252日前收盘价）
        if len(df) >= 252:
            price_1y = df["close"].iloc[-252]
            ret_1y = (now / price_1y - 1) * 100
        else:
            price_1y = df["close"].iloc[0]
            ret_1y = (now / price_1y - 1) * 100

        # 回撤幅度
        drawdown = (high_252 - now) / high_252 if high_252 > 0 else 0

        # 股价位置评分
        # 0.8-1.0 (高位): 分数低，因为利好已反映
        # 0.5-0.8 (中部): 分数中等
        # 0.3-0.5 (低位): 分数高，有补涨空间
        # <0.3 (超跌): 分数高，但可能是基本面恶化
        if price_position >= 0.9:
            position_score = 2.0
        elif price_position >= 0.75:
            position_score = 4.0
        elif price_position >= 0.55:
            position_score = 6.5
        elif price_position >= 0.35:
            position_score = 8.5
        else:
            position_score = 7.0  # 超跌但要注意是否基本面恶化

        # 特殊处理：供需利好已经price in
        # 如果1年涨幅>100%且当前在高位，给高分但降权重
        if ret_1y > 150 and price_position > 0.85:
            position_score = 3.0  # 已涨太多，谨慎
        elif ret_1y > 80 and price_position > 0.80:
            position_score = 4.0

        return position_score, price_position, ret_1y

    except Exception:
        return 5.0, 1.0, 0.0


def get_news_score(segment: str, ticker: str) -> float:
    """
    新闻催化评分 (0-10)
    基于近期新闻量和关键词判断
    """
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent / "data" / "cache" / "quant_data.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # 近期90天内含该环节关键词的新闻数量
        keywords = {
            "光模块": ["光模块", "800G", "1.6T", "光通信"],
            "光芯片": ["光芯片", "VCSEL", "DFB", "激光器"],
            "存储制造": ["存储", "NAND", "DRAM", "HBM"],
            "减速器": ["减速器", "谐波", "RV减速"],
            "正极材料": ["正极", "三元", "磷酸铁锂"],
            "负极材料": ["负极", "石墨"],
            "隔膜": ["隔膜", "湿法隔膜"],
            "电解液": ["电解液"],
            "电芯/PACK": ["电芯", "动力电池", "储能电池"],
            "伺服驱动": ["伺服", "伺服驱动"],
            "控制器": ["控制器", "PLC", "数控"],
            "传感器": ["传感器", "MEMS", "力传感器"],
            "机器人本体": ["人形机器人", "工业机器人"],
            "高温合金/钛合金": ["高温合金", "钛合金"],
            "航发整机": ["航发", "航空发动机"],
            "军机/无人机": ["军机", "无人机", "军用飞机"],
            "导弹/精确制导": ["导弹", "制导"],
            "军工信息化": ["军工", "连接器", "信息化"],
            "商业航天": ["商业航天", "卫星", "火箭"],
        }

        seg_keywords = keywords.get(segment, [segment])
        like_clause = " OR ".join([f"title LIKE '%{k}%'" for k in seg_keywords])

        cur.execute(f"""
            SELECT COUNT(*) FROM news_items
            WHERE ({like_clause})
            AND datetime(published_at) > datetime('now', '-90 days')
        """)
        count = cur.fetchone()[0]
        conn.close()

        # 新闻数量 → 催化强度
        if count >= 20:
            return 8.0
        elif count >= 10:
            return 6.5
        elif count >= 5:
            return 5.0
        elif count >= 2:
            return 4.0
        elif count >= 1:
            return 3.0
        else:
            return 2.0  # 有供需缺口但新闻少，可能被忽视

    except Exception:
        return 5.0


def calculate_gap_trend(segment: str) -> str:
    """供需缺口趋势：未来3/6/9个月是扩大还是收窄"""
    g0 = get_supply_demand_gap(segment, 0)
    g6 = get_supply_demand_gap(segment, 6)
    g12 = get_supply_demand_gap(segment, 12)

    if g12["gap_pct"] > g0["gap_pct"] + 2:
        return "扩大"
    elif g12["gap_pct"] < g0["gap_pct"] - 2:
        return "收窄"
    else:
        return "持平"


def score_segment_stocks(segment: str) -> list[StockSignal]:
    """
    对某环节所有股票打分
    """
    stocks = get_stock_by_segment(segment)
    if not stocks:
        return []

    cycle_score, phase = get_cycle_score(segment)
    gap = get_supply_demand_gap(segment, 0)
    gap_trend = calculate_gap_trend(segment)
    news_score = get_news_score(segment, "")

    signals = []
    for ticker, name in stocks:
        position_score, price_pos, ret_1y = get_position_score(ticker, name, segment)

        # 综合分 = 供需分×0.4 + 位置分×0.3 + 新闻×0.3
        total = cycle_score * 0.4 + position_score * 0.3 + news_score * 0.3

        # 信号类型
        if total >= 8.0:
            signal_type = "🚀 强烈买入"
        elif total >= 6.5:
            signal_type = "📈 关注"
        elif total >= 5.0:
            signal_type = "⏸️ 观望"
        else:
            signal_type = "❄️ 回避"

        signals.append(StockSignal(
            ticker=ticker,
            name=name,
            segment=segment,
            cycle_phase=phase,
            gap_pct=gap["gap_pct"],
            gap_trend=gap_trend,
            price_position=price_pos,
            price_1y_ret=ret_1y,
            news催化剂=news_score,
            cycle_score=cycle_score,
            position_score=position_score,
            total_score=round(total, 1),
            signal_type=signal_type,
        ))

    return signals


def print_signal_report(signals: list[StockSignal], segment: str = ""):
    """打印信号报告"""
    if not signals:
        print(f"  (无数据)")
        return

    # 按综合分排序
    signals.sort(key=lambda x: x.total_score, reverse=True)

    print(f"\n{'─'*70}")
    print(f"{'📊 '+segment+' 信号评分' if segment else '📊 全市场信号'}")
    print(f"{'─'*70}")
    print(f"{'代码':<8}{'名称':<10}{'周期':<6}{'缺口':<8}{'位置':<8}{'1年涨跌':<10}{'综合分':<6}{'信号'}")
    print(f"{'─'*70}")

    for s in signals:
        pos_str = f"{s.price_position:.0%}"
        ret_str = f"{s.price_1y_ret:+.0f}%"
        print(f"{s.ticker:<8}{s.name:<10}{s.cycle_phase:<6}"
              f"{s.gap_pct:+.0f}%{'':<4}{pos_str:<8}{ret_str:<10}"
              f"{s.total_score:<6.1f}{s.signal_type}")


def scan_all_segments(top_n: int = 20) -> list[StockSignal]:
    """扫描所有环节，打印Top信号"""
    all_signals = []
    for seg in get_all_chain_segments():
        sigs = score_segment_stocks(seg)
        all_signals.extend(sigs)

    all_signals.sort(key=lambda x: x.total_score, reverse=True)
    return all_signals[:top_n]


# ──────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="供需信号评分")
    parser.add_argument("--segment", type=str, default="", help="只看某环节")
    parser.add_argument("--top", type=int, default=0, help="TopN信号（默认全扫）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细分数")
    args = parser.parse_args()

    if args.segment:
        print(f"\n{'='*70}")
        print(f"🔍 环节分析: {args.segment}")
        print(f"{'='*70}")

        # 显示环节供需状态
        gap = get_supply_demand_gap(args.segment, 0)
        cycle_score, phase = get_cycle_score(args.segment)
        gap_trend = calculate_gap_trend(args.segment)
        news_score = get_news_score(args.segment, "")

        print(f"  供需周期: {phase}")
        print(f"  当前缺口: {gap['gap_pct']:+.1f}% ({gap['status']})")
        print(f"  趋势: {gap_trend}")
        print(f"  新闻催化: {news_score:.1f}/10")

        print(f"\n  各公司在当前位置:")
        signals = score_segment_stocks(args.segment)
        print_signal_report(signals)

        # 各公司产能利用率
        entries = [e for e in CAPACITY_DATABASE if e.segment == args.segment]
        if entries:
            print(f"\n  产能利用率:")
            for e in entries:
                icon = "🔴" if e.utilization > 0.90 else ("🟡" if e.utilization > 0.75 else "🟢")
                print(f"    {icon} {e.company}: {e.capacity_current}{e.capacity_unit} 利用率={e.utilization*100:.0f}%")

    elif args.top > 0:
        print(f"\n{'='*70}")
        print(f"🏆 Top{args.top} 供需信号")
        print(f"{'='*70}")
        top_signals = scan_all_segments(args.top)
        for i, s in enumerate(top_signals, 1):
            print(f"\n{i}. {s.name}({s.ticker}) | {s.segment}")
            print(f"   周期:{s.cycle_phase} 缺口:{s.gap_pct:+.0f}% 位置:{s.price_position:.0%} 1年涨跌:{s.price_1y_ret:+.0f}%")
            print(f"   供需分:{s.cycle_score:.1f} 位置分:{s.position_score:.1f} 新闻:{s.news催化剂:.1f}")
            print(f"   → {s.signal_type} (综合{s.total_score:.1f})")
    else:
        # 全市场各环节总览
        print(f"\n{'='*70}")
        print(f"📊 全产业链供需信号总览")
        print(f"{'='*70}")
        print(f"{'环节':<20}{'周期':<6}{'缺口':<8}{'趋势':<8}{'催化':<6}{'均分'}")
        print(f"{'─'*70}")

        for seg in sorted(get_all_chain_segments()):
            gap = get_supply_demand_gap(seg, 0)
            cycle_score, phase = get_cycle_score(seg)
            gap_trend = calculate_gap_trend(seg)
            news_score = get_news_score(seg, "")

            # 该环节所有股平均位置分
            stocks = get_stock_by_segment(seg)
            pos_scores = []
            for t, n in stocks:
                ps, _, _ = get_position_score(t, n, seg)
                pos_scores.append(ps)
            avg_pos = sum(pos_scores) / len(pos_scores) if pos_scores else 5.0

            avg_total = cycle_score * 0.4 + avg_pos * 0.3 + news_score * 0.3

            icon = "🔴" if cycle_score >= 7 else ("🟡" if cycle_score >= 5 else "🟢")
            print(f"{seg:<20}{phase:<6}{gap['gap_pct']:+.0f}%{'':<4}{gap_trend:<8}{news_score:.1f}{'':<3}{avg_total:.1f}{icon}")

        print(f"\n{'─'*70}")
        print("说明: 综合分 = 供需分×40% + 股价位置×30% + 新闻催化×30%")
        print("      缺口>0为紧缺，<0为过剩；位置<55%为相对低位，>80%为高位")


if __name__ == "__main__":
    main()
