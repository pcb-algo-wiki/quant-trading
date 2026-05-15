#!/usr/bin/env python3
"""
个股每日扫描 + 微信推送
==========================
每日自动推送:
  - 半导体板块 Top5 Buy/Hold/Sell
  - 核心30只 Top5
  - 危险持仓警告

用法:
  python scripts/stock_daily.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from data.stock_screener import scan_stocks, format_scan_results
from data.stock_pool import get_pool, ALL_STOCKS, SEMI_CONDUCTOR
from data.stock_pool import AI_COMPUTE, AI_APPLICATION, OPTICAL_COMMS, COMMS_EQUIPMENT
from data.stock_pool import SEMI_CONDUCTOR as SEMI_POOL, NEW_ENERGY_VEHICLE, DEFENSE, AEROSPACE, CONSUMER, FINANCE
from utils.notify import pushplus_send


def generate_stock_report() -> str:
    """生成个股日报（全部产业链）"""
    lines = []

    # 各板块定义
    pools = [
        ("AI算力", AI_COMPUTE),
        ("AI应用", AI_APPLICATION),
        ("光通信", OPTICAL_COMMS),
        ("通信设备", COMMS_EQUIPMENT),
        ("半导体", SEMI_POOL),
        ("新能源车", NEW_ENERGY_VEHICLE),
        ("军工", DEFENSE),
        ("航天", AEROSPACE),
    ]

    all_buys = []
    all_sells = []

    for sector_name, pool in pools:
        df = scan_stocks(pool, use_cache=True)
        buys = df[df["signal"] == "Buy"].head(3)
        sells = df[df["signal"] == "Sell"].head(2)
        all_buys.extend([(r, sector_name) for _, r in buys.iterrows()])
        all_sells.extend([(r, sector_name) for _, r in sells.iterrows()])

        lines.append(f"{'='*50}")
        lines.append(f"📊 {sector_name} ({len(pool)}只, Buy {len(buys)}只)")
        lines.append(f"{'='*50}")

        if len(buys) > 0:
            lines.append("🟢 买入:")
            for _, r in buys.iterrows():
                lines.append(f"  {r['symbol']} {r['name']:<8} 得{r['score']:.0f} 20日{r['ret_20d']:+.1f}%")
        if len(sells) > 0:
            lines.append("🔴 卖出:")
            for _, r in sells.iterrows():
                lines.append(f"  {r['symbol']} {r['name']:<8} 得{r['score']:.0f} 20日{r['ret_20d']:+.1f}%")
        lines.append("")

    # 综合Top10
    lines.append(f"{'='*50}")
    lines.append("🏆 综合得分Top10")
    lines.append(f"{'='*50}")

    df_all = scan_stocks(ALL_STOCKS, use_cache=True)
    top10 = df_all.head(10)
    for i, (_, r) in enumerate(top10.iterrows(), 1):
        lines.append(f"  {i:2}. {r['symbol']} {r['name']:<8} [{r['sector']}] 得{r['score']:.0f} {r['signal']}")

    # 危险持仓
    sells_top = df_all[df_all["signal"] == "Sell"].head(5)
    if len(sells_top) > 0:
        lines.append("")
        lines.append("⚠️ 建议卖出(趋势向下):")
        for _, r in sells_top.iterrows():
            lines.append(f"  {r['symbol']} {r['name']:<8} [{r['sector']}] 得{r['score']:.0f} 20日{r['ret_20d']:+.1f}%")

    # 统计
    total_buys = (df_all["signal"] == "Buy").sum()
    total_sells = (df_all["signal"] == "Sell").sum()
    lines.append(f"\n📈 整体: {total_buys}只Buy / {total_sells}只Sell / {len(df_all)}只")

    return "\n".join(lines)


if __name__ == "__main__":
    import datetime
    print(f"=== 个股日报 {datetime.date.today()} ===\n")

    report = generate_stock_report()
    print(report)

    # 推送到微信
    print("\n推送到微信...")
    try:
        pushplus_send(f"个股日报 {datetime.date.today()}", report)
        print("推送成功")
    except Exception as e:
        print(f"推送失败: {e}")
