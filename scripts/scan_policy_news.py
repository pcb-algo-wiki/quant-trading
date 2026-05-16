#!/usr/bin/env python3
"""产业链潜力股 — 结合政策/新闻关注度 + 股价位置"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from data.stock_screener import scan_stocks
from data.stock_pool import SEMI_CONDUCTOR, OPTICAL_COMMS

chain_pool = {}
chain_pool.update(SEMI_CONDUCTOR)
chain_pool.update(OPTICAL_COMMS)

print('扫描产业链技术面...')
df = scan_stocks(chain_pool, use_cache=True)

conn = sqlite3.connect('data/cache/quant_data.db')
cur = conn.cursor()

# 知识库 evidence 统计
ev = {}
rows = cur.execute("""
    SELECT n.node_id, n.name, COUNT(e.doc_hash) as cnt
    FROM knowledge_nodes n
    LEFT JOIN knowledge_evidence e ON e.node_id = n.node_id
    WHERE n.type='company'
    GROUP BY n.node_id
""").fetchall()
for node_id, name, cnt in rows:
    ev[node_id] = cnt

# 近30天行业事件（高sentiment_score/policy_score = 正面新闻/政策催化）
events = cur.execute("""
    SELECT symbol, title, sentiment_score, policy_score, event_type
    FROM industry_events
    WHERE published_at > date('now', '-30 days')
    AND (sentiment_score > 0 OR policy_score > 0)
    ORDER BY sentiment_score DESC, policy_score DESC
""").fetchall()

event_symbols = {}
for sym, title, sent, pol, etype in events:
    if not sym or sym == 'N/A':
        continue
    if sym not in event_symbols:
        event_symbols[sym] = {'sent': 0, 'pol': 0, 'titles': []}
    event_symbols[sym]['sent'] = max(event_symbols[sym]['sent'], sent or 0)
    event_symbols[sym]['pol'] = max(event_symbols[sym]['pol'], pol or 0)
    if len(event_symbols[sym]['titles']) < 2:
        event_symbols[sym]['titles'].append(title[:40])

# 近30天新闻数量
news_cnt = cur.execute("""
    SELECT related_symbol, COUNT(*) as cnt
    FROM news_items
    WHERE published_at > date('now', '-30 days')
    AND related_symbol IS NOT NULL
    GROUP BY related_symbol
""").fetchall()
news_map = {r[0]: r[1] for r in news_cnt}
conn.close()

# 合并
df['evidence'] = df['symbol'].map(lambda s: ev.get(s, 0))
df['event_sent'] = df['symbol'].map(lambda s: event_symbols.get(s, {}).get('sent', 0))
df['event_pol'] = df['symbol'].map(lambda s: event_symbols.get(s, {}).get('pol', 0))
df['news_count'] = df['symbol'].map(lambda s: news_map.get(s, 0))

# 潜力分 = 知识库证据*0.3 + 新闻数*2 + 政策分*10 + 情绪分*5
df['潜力分'] = (
    df['evidence'] * 0.3 +
    df['news_count'] * 2 +
    df['event_pol'] * 10 +
    df['event_sent'] * 5
)

# 筛选：还没大涨但有催化（政策/新闻关注）
催化 = df[
    (df['ret_20d'] < 40) &
    ((df['event_pol'] > 0) | (df['news_count'] > 5) | (df['evidence'] > 5))
].sort_values('潜力分', ascending=False)

print()
print('='*95)
print('  产业链潜力股 — 政策/新闻催化 + 股价未充分上涨')
print('='*95)
print(f'  筛选出 {len(催化)} 只\n')
print(f'  {"代码":<8} {"名称":<8} {"细分":<14} {"评分":<5} {"20日":<9} {"新闻":<6} {"证据":<5} {"政策分":<7} {"潜力分"}')
print(f'  {"-"*90}')

for _, r in 催化.head(25).iterrows():
    pol = r['event_pol']
    pol_icon = '�的政策' if pol > 3 else '📋' if pol > 0 else ''
    print(f"  {r['symbol']:<8} {r['name']:<8} {r['industry']:<14} {r['score']:.0f}     {r['ret_20d']:+.1f}%    {r['news_count']:<6} {r['evidence']:<5} {pol:>5.1f}    {r['潜力分']:.1f}  {pol_icon}")

print()
print('=== 近期催化事件（政策/行业利好）===')
all_events = []
for sym, info in event_symbols.items():
    if info['pol'] > 0 or info['sent'] > 0.2:
        all_events.append((sym, info))

all_events.sort(key=lambda x: (x[1]['pol'], x[1]['sent']), reverse=True)
for sym, info in all_events[:20]:
    print(f"  [{sym}] 政策={info['pol']:.1f} 情绪={info['sent']:.2f}")
    for t in info['titles']:
        print(f"    → {t}")
