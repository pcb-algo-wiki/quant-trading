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
from data.stock_fetcher import SEMI_CONDUCTOR_STOCKS, CORE_30_STOCKS
from utils.notify import pushplus_send


def generate_stock_report() -> str:
    """生成个股日报"""
    lines = []

    # 1. 半导体板块扫描
    lines.append("=" * 60)
    lines.append("📊 半导体/光伏板块个股扫描")
    lines.append("=" * 60)

    df_semi = scan_stocks(SEMI_CONDUCTOR_STOCKS, use_cache=True)
    buys = df_semi[df_semi["signal"] == "Buy"].head(5)
    holds = df_semi[df_semi["signal"] == "Hold"].head(3)
    sells = df_semi[df_semi["signal"] == "Sell"].head(3)

    if len(buys) > 0:
        lines.append("\n🟢 建议买入:")
        for _, r in buys.iterrows():
            lines.append(f"  {r['symbol']} {r['name']:<8} 得分{r['score']} 20日{r['ret_20d']:.1f}% 趋势{r['trend_strength']:.2f}%")

    if len(holds) > 0:
        lines.append("\n🟡 观望:")
        for _, r in holds.iterrows():
            lines.append(f"  {r['symbol']} {r['name']:<8} 得分{r['score']} 20日{r['ret_20d']:.1f}%")

    if len(sells) > 0:
        lines.append("\n🔴 建议卖出:")
        for _, r in sells.iterrows():
            lines.append(f"  {r['symbol']} {r['name']:<8} 得分{r['score']} 20日{r['ret_20d']:.1f}%")

    # 2. 核心30只
    lines.append("\n" + "=" * 60)
    lines.append("📊 核心30只龙头股扫描")
    lines.append("=" * 60)

    df_core = scan_stocks(CORE_30_STOCKS, use_cache=True)
    df_core_slim = df_core[["symbol", "name", "signal", "score", "ret_20d", "trend_strength"]].copy()
    df_core_slim["ret_20d"] = df_core_slim["ret_20d"].apply(lambda x: f"{x:.1f}%" if x else "N/A")
    df_core_slim["trend_strength"] = df_core_slim["trend_strength"].apply(lambda x: f"{x:.2f}%" if x else "N/A")

    buys_core = df_core[df_core["signal"] == "Buy"].head(5)
    sells_core = df_core[df_core["signal"] == "Sell"].head(5)

    if len(buys_core) > 0:
        lines.append("\n🟢 建议买入:")
        for _, r in buys_core.iterrows():
            lines.append(f"  {r['symbol']} {r['name']:<8} 得分{r['score']} 20日{r['ret_20d']:.1f}%")

    if len(sells_core) > 0:
        lines.append("\n🔴 建议卖出:")
        for _, r in sells_core.iterrows():
            lines.append(f"  {r['symbol']} {r['name']:<8} 得分{r['score']} 20日{r['ret_20d']:.1f}%")

    # 3. 总结
    buy_count_semi = (df_semi["signal"] == "Buy").sum()
    buy_count_core = (df_core["signal"] == "Buy").sum()
    lines.append(f"\n📈 整体信号: 半导体{buy_count_semi}只Buy / 核心{buy_count_core}只Buy")

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
