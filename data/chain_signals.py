"""
data/chain_signals.py
=====================
产业链信号源接入 — 自动从新闻/政策检测趋势信号

功能:
  1. 从多源新闻（realtime_news）获取实时信息
  2. 用 detect_trend_signal 匹配产业链关键词
  3. 自动记录趋势事件到 IndustryEventDB
  4. 生成综合 ChainSignal 并输出报告

用法:
  python data/chain_signals.py          # 运行信号检测+报告
  python data/chain_signals.py --watch  # 持续监控模式
"""

import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import json

# 导入同目录模块
from industry_chain import (
    INDUSTRY_CHAINS, list_chains, get_chain_info,
    generate_chain_signal, TrendSignal, IndustryEventDB,
    ChainSignal, CACHE_DIR
)

# 导入新闻模块
sys.path.insert(0, str(Path(__file__).parent))
try:
    from realtime_news import get_realtime_news, get_policy_news, sentiment_score
except ImportError:
    # 如果realtime_news不可用，提供备用
    def get_realtime_news() -> pd.DataFrame:
        return pd.DataFrame()
    def get_policy_news(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame()
    def sentiment_score(text: str) -> float:
        return 0.5

# ============ 配置 ============

SIGNAL_CACHE = CACHE_DIR / "chain_signal_cache.json"
DEDUP_WINDOW_HOURS = 6  # 6小时内同一关键词/产业链只记录一次


# ============ 信号检测 ============

def scan_news_for_signals(df: pd.DataFrame) -> List[Dict]:
    """
    扫描新闻DataFrame，检测产业链趋势信号

    Returns:
        List of detected signals with metadata
    """
    from industry_chain import detect_trend_signal

    all_signals = []
    seen_titles = set()  # 去重：同一天同一产业链，标题相似不重复

    for _, row in df.iterrows():
        title = str(row.get('title', ''))
        content = str(row.get('content', ''))
        news_time = row.get('datetime', datetime.now())
        source = row.get('source', 'unknown')

        # 合并标题+内容
        full_text = f"{title} {content}".strip()
        if len(full_text) < 10:
            continue

        # 检测信号
        signals = detect_trend_signal(full_text, news_time.strftime('%Y-%m-%d') if pd.notna(news_time) else None)

        for sig in signals:
            # 用真实新闻标题的前60字去重
            title_short = title[:60]
            dedup_key = (sig['chain_key'], sig['date'][:10], title_short)
            if dedup_key in seen_titles:
                continue
            seen_titles.add(dedup_key)

            # 过滤低强度信号
            if sig['strength'] < 0.6:
                continue

            sig['source'] = source
            sig['news_title'] = title[:200]
            all_signals.append(sig)

    return all_signals


def get_trending_chains(days: int = 7) -> pd.DataFrame:
    """
    获取近期最热门的产业链（基于信号频率）
    """
    all_events = []

    for chain_key in list_chains():
        db = IndustryEventDB(chain_key)
        events = db.get_events(days=days)
        all_events.extend([{
            'chain_key': chain_key,
            'date': e.date,
            'signal_type': e.signal_type.value,
            'title': e.title,
        } for e in events])

    if not all_events:
        return pd.DataFrame()

    df = pd.DataFrame(all_events)

    # 统计每个产业链的信号频率
    chain_counts = df.groupby('chain_key').size().reset_index(name='signal_count')

    # 最近的信号
    latest = df.sort_values('date').groupby('chain_key').last().reset_index()

    result = chain_counts.merge(latest, on='chain_key')
    result = result.sort_values('signal_count', ascending=False)
    return result


def get_chain_news_matrix() -> pd.DataFrame:
    """
    获取最新新闻，按产业链×情感构成矩阵
    """
    df = get_realtime_news()
    if df.empty:
        return pd.DataFrame()

    # 扫描信号
    signals = scan_news_for_signals(df)

    if not signals:
        return pd.DataFrame()

    # 构建矩阵
    matrix = []
    for sig in signals:
        matrix.append({
            'datetime': sig.get('datetime', ''),
            'chain': sig['chain'],
            'chain_key': sig['chain_key'],
            'keyword': sig['keyword'],
            'strength': sig['strength'],
            'impacted_nodes': ', '.join(sig['impacted_nodes'][:3]),
            'title': sig.get('news_title', sig.get('title', ''))[:100],
            'source': sig.get('source', ''),
        })

    return pd.DataFrame(matrix)


# ============ 事件自动记录 ============

def auto_record_events(df: pd.DataFrame, min_strength: float = 0.6) -> Dict[str, int]:
    """
    自动将检测到的信号记录到事件库

    Returns:
        {chain_key: recorded_count}
    """
    from industry_chain import TrendEvent

    signals = scan_news_for_signals(df)
    recorded = {}

    for sig in signals:
        if sig['strength'] < min_strength:
            continue

        chain_key = sig['chain_key']
        if chain_key not in recorded:
            recorded[chain_key] = 0

        # 构造事件
        event = TrendEvent(
            date=sig['date'],
            signal_type=TrendSignal.POLICY if sig['strength'] >= 1.0 else TrendSignal.CAPITAL,
            trend=sig['chain'],
            title=sig.get('news_title', sig.get('title', ''))[:100],
            description=f"关键词: {sig['keyword']}, 强度: {sig['strength']:.1f}",
            impacted_nodes=sig['impacted_nodes'],
            policy_strength=sig['strength'],
            market_response="待回测",
        )

        db = IndustryEventDB(chain_key)
        db.add_event(event)
        recorded[chain_key] += 1

    return recorded


# ============ 报告生成 ============

def generate_daily_report() -> str:
    """
    生成每日产业链分析报告
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"  📊 产业链信号日报 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)

    # 1. 获取最新新闻
    t0 = time.time()
    df = get_realtime_news()
    lines.append(f"\n📰 今日新闻扫描: {len(df)}条 (耗时 {time.time()-t0:.1f}s)")

    if df.empty:
        lines.append("  (无法获取新闻，请检查网络)")
        return '\n'.join(lines)

    # 2. 扫描产业链信号
    signals = scan_news_for_signals(df)
    lines.append(f"🔍 检测到产业链信号: {len(signals)}条")

    # 按强度排序
    if signals:
        signals.sort(key=lambda x: x['strength'], reverse=True)
        lines.append("\n【重点信号】")
        for sig in signals[:5]:
            lines.append(f"  {'🔥' if sig['strength'] >= 1.0 else '⚡'} [{sig['chain']}] {sig['keyword']}")
            lines.append(f"      {sig.get('news_title', sig.get('title', ''))[:80]}")
            lines.append(f"      → 影响节点: {', '.join(sig['impacted_nodes'][:3])}")

    # 3. 自动记录
    lines.append("\n【事件记录】")
    try:
        recorded = auto_record_events(df)
        if recorded:
            for k, v in recorded.items():
                lines.append(f"  ✅ {INDUSTRY_CHAINS[k].trend}: +{v}条事件")
        else:
            lines.append("  (今日无新增)")
    except Exception as e:
        lines.append(f"  (记录失败: {e})")

    # 4. 各产业链信号
    lines.append("\n【产业链信号】")
    for chain_key in list_chains():
        try:
            sig = generate_chain_signal(chain_key)
            emoji = '🟢' if sig.action == 'buy' else '🔄' if sig.action == 'rotate' else '⚪'
            lines.append(f"  {emoji} {sig.chain}")
            lines.append(f"      综合:{sig.composite} | {sig.cycle_position}期 | 操作:{sig.action}")
            lines.append(f"      {sig.reason}")
            if sig.top_picks:
                lines.append(f"      首选: {', '.join(sig.top_picks[:3])}")
        except Exception as e:
            lines.append(f"  ❌ {chain_key}: {e}")

    # 5. 热门产业链
    lines.append("\n【近期热度榜】(7日)")
    trending = get_trending_chains(days=7)
    if not trending.empty:
        for i, row in trending.head(5).iterrows():
            lines.append(f"  {i+1}. {row['chain_key']}: {row['signal_count']}条信号")
    else:
        lines.append("  (暂无数据)")

    lines.append("\n" + "=" * 70)
    return '\n'.join(lines)


def get_watch_report() -> str:
    """
    持续监控模式报告（精简版）
    """
    df = get_realtime_news()
    if df.empty:
        return "⚠️ 无法获取新闻"

    signals = scan_news_for_signals(df)

    lines = []
    lines.append(f"📊 监控 | {datetime.now().strftime('%H:%M:%S')} | {len(df)}条新闻 | {len(signals)}个信号")

    if signals:
        # 按产业链聚合
        chain_signals = {}
        for s in signals:
            k = s['chain_key']
            if k not in chain_signals:
                chain_signals[k] = []
            chain_signals[k].append(s)

        for k, slist in sorted(chain_signals.items(), key=lambda x: -len(x[1])):
            top = max(slist, key=lambda x: x['strength'])
            emoji = '🔥' if top['strength'] >= 1.0 else '⚡'
            lines.append(f"  {emoji} {k}: {len(slist)}条 | 最高强度{top['strength']:.1f} [{top['keyword']}]")

    return '\n'.join(lines)


# ============ 主程序 ============

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='产业链信号检测')
    parser.add_argument('--watch', action='store_true', help='持续监控模式')
    parser.add_argument('--interval', type=int, default=60, help='监控间隔(秒)')
    parser.add_argument('--limit', type=int, default=20, help='显示条数')
    args = parser.parse_args()

    if args.watch:
        print(f"🔍 启动监控模式 (间隔{args.interval}秒, Ctrl+C退出)")
        print("-" * 50)
        try:
            while True:
                report = get_watch_report()
                print(report)
                print("-" * 50)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n👋 监控已停止")
    else:
        report = generate_daily_report()
        print(report)
