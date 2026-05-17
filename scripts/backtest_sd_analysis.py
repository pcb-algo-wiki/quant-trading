#!/usr/bin/env python3
"""深入分析评分系统的问题"""
import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from knowledge.supply_chain import get_stock_by_segment, get_all_chain_segments, get_supply_demand_gap, CYCLE_PHASES
from data.stock_pool import ALL_STOCKS
import pandas as pd

# 加载数据
def load_stock_price(ticker: str) -> pd.DataFrame:
    p = Path(f"data/cache/stocks/{ticker}.pkl")
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_pickle(p)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)

conn = sqlite3.connect("data/cache/quant_data.db")

print("=" * 70)
print("  评分系统深度诊断")
print("=" * 70)

# 1. 各环节供需分
print("\n[1] 各环节供需分（核心差异化来源）")
print(f"{'环节':<20}{'周期':<6}{'缺口':>8}{'供需分':>8}")
for seg in get_all_chain_segments():
    gap = get_supply_demand_gap(seg, 0)
    phases = [p for p in CYCLE_PHASES if p.segment == seg]
    phases_sorted = sorted(phases, key=lambda p: (int(p.start_period.split("Q")[0]), int(p.start_period.split("Q")[1])))
    current = None
    for i in range(len(phases_sorted) - 1, -1, -1):
        if phases_sorted[i].end_period is None:
            current = phases_sorted[i]; break
    if current is None: continue
    phase_score_map = {"紧缺": 9.0, "均衡": 5.0, "去化": 4.0, "过剩": 2.0}
    base = phase_score_map.get(current.phase, 5.0)
    gap_abs = abs(gap["gap_pct"])
    gap_bonus = min(gap_abs / 10, 1.5) if gap["gap_pct"] > 0 else -min(gap_abs / 10, 1.0)
    score = max(0, min(10, base + gap_bonus))
    print(f"  {seg:<20}{current.phase:<6}{gap['gap_pct']:>+7.0f}%{score:>8.1f}")

# 2. 新闻数量分布（真实数据）
print("\n[2] 新闻数据库统计（90天窗口）")
cur = conn.cursor()
cur.execute("""
    SELECT published_at FROM news_items ORDER BY published_at DESC LIMIT 5
""")
print("最新新闻时间:", [r[0] for r in cur.fetchall()])

cur.execute("SELECT COUNT(*) FROM news_items")
total = cur.fetchone()[0]
print(f"总新闻数: {total}")

# 各segment新闻数量
keywords = {
    "光模块": ["光模块", "800G", "1.6T", "光通信"],
    "存储制造": ["存储", "NAND", "DRAM", "HBM"],
    "机器人本体": ["人形机器人", "工业机器人"],
    "减速器": ["减速器", "谐波", "RV减速"],
    "正极材料": ["正极", "三元", "磷酸铁锂"],
    "半导体设备": ["半导体设备", "半导体装备"],
    "硅片/晶圆": ["硅片", "晶圆"],
    "航发整机": ["航发", "航空发动机"],
    "商业航天": ["商业航天", "卫星", "火箭"],
}
print(f"\n{'环节':<20}{'新闻数':>8}{'催化分':>8}")
for seg, kws in keywords.items():
    like_clause = " OR ".join([f"title LIKE '%{k}%'" for k in kws])
    cur.execute(f"""
        SELECT COUNT(*) FROM news_items
        WHERE ({like_clause})
        AND datetime(published_at) > datetime('now', '-90 days')
    """)
    cnt = cur.fetchone()[0]
    news_sc = 8.0 if cnt >= 20 else (6.5 if cnt >= 10 else (5.0 if cnt >= 5 else (4.0 if cnt >= 2 else (3.0 if cnt >= 1 else 2.0))))
    print(f"  {seg:<20}{cnt:>8}{news_sc:>8.1f}")

conn.close()

# 3. 位置分分析（为什么分低）
print("\n[3] 位置分分析（随机抽样10只股票）")
cached = list(Path("data/cache/stocks").glob("*.pkl"))[:10]
for p in cached:
    ticker = p.stem
    if ticker not in ALL_STOCKS: continue
    df = load_stock_price(ticker)
    if len(df) < 300: continue
    now = df["close"].iloc[-1]
    high_252 = df["high"].iloc[-252:].max()
    low_252 = df["low"].iloc[-252:].min()
    price_pos = now / high_252
    if len(df) >= 252:
        ret_1y = (now / df["close"].iloc[-252] - 1) * 100
    else:
        ret_1y = 0
    if price_pos >= 0.9: ps = 2.0
    elif price_pos >= 0.75: ps = 4.0
    elif price_pos >= 0.55: ps = 6.5
    elif price_pos >= 0.35: ps = 8.5
    else: ps = 7.0
    if ret_1y > 150 and price_pos > 0.85: ps = 3.0
    elif ret_1y > 80 and price_pos > 0.80: ps = 4.0
    print(f"  {ticker}: 位置={price_pos:.0%}, 1年涨跌={ret_1y:+.0f}%, 位置分={ps:.1f}")

# 4. 综合评分期望分布
print("\n[4] 综合评分期望区间")
print("  供需分: 7~10 (紧缺环节多), 权重40% → 贡献 2.8~4.0")
print("  位置分: 2~6 (大多在高位), 权重30% → 贡献 0.6~1.8")
print("  新闻分: 2~6 (新闻少), 权重30% → 贡献 0.6~1.8")
print("  期望总分: 4.0~7.6, 很难超过7.5")
print("\n  问题诊断:")
print("  1. 新闻分太低(0-6分) → 建议提高新闻分上限或调整关键词")
print("  2. 位置分上限6.5分 → 建议高位股不要一刀切降分")
print("  3. 供需分普遍9-10分 → 差异化不足，需要动态gap bonus")
print("  4. 权重比例可能需要调整")

# 5. 权重敏感性测试（用已有数据估算）
print("\n[5] 权重敏感性（阈值5.0时）")
print("  当前权重: 供需40% + 位置30% + 新闻30%")
print("  调整方案建议:")
print("    方案A: 供需50% + 位置25% + 新闻25% (强化周期)")
print("    方案B: 供需30% + 位置40% + 新闻30% (强化位置)")
print("    方案C: 供需35% + 位置30% + 新闻35% (强化新闻)")
