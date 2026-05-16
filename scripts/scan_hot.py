#!/usr/bin/env python3
"""产业链热点扫描 — 结合新闻热度 + 股价位置"""
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

# 知识库 evidence：每家公司被多少篇新闻提到
ev_data = {}
rows = cur.execute("""
    SELECT e.node_id, COUNT(*) as cnt
    FROM knowledge_evidence e
    JOIN knowledge_nodes n ON n.node_id = e.node_id
    WHERE n.type='company'
    GROUP BY e.node_id
""").fetchall()
for node_id, cnt in rows:
    ev_data[node_id] = cnt

# 近7天新闻全文（从news_items匹配产业链关键词）
recent = cur.execute("""
    SELECT title, content
    FROM news_items
    WHERE content IS NOT NULL AND content != '' AND content != 'nan'
    AND published_at > date('now', '-7 days')
    ORDER BY published_at DESC
    LIMIT 200
""").fetchall()

keywords = {
    '拓荆科技': ['拓荆', 'PECVD', 'CVD设备'],
    '中科飞测': ['中科飞测', '量测'],
    '华大九天': ['华大九天', 'EDA'],
    '北方华创': ['北方华创', '刻蚀设备'],
    '中微公司': ['中微', '刻蚀'],
    '天岳先进': ['天岳', 'SiC', '碳化硅'],
    '有研硅': ['有研硅'],
    '源杰科技': ['源杰', '光芯片', '激光器'],
    '南亚新材': ['南亚新材', 'CCL', '覆铜板'],
    '博创科技': ['博创', 'PLC'],
    '天孚通信': ['天孚'],
    '仕佳光子': ['仕佳光子'],
    '沪硅产业': ['沪硅'],
    '生益科技': ['生益'],
    '通富微电': ['通富'],
    '长电科技': ['长电'],
    '中际旭创': ['中际旭创', 'CPO'],
    '新易盛': ['新易盛'],
    '剑桥科技': ['剑桥'],
    '韦尔股份': ['韦尔', 'CIS'],
    '三安光电': ['三安光电'],
    '华虹半导体': ['华虹'],
    '华润微': ['华润微'],
    '卓胜微': ['卓胜微'],
    '寒武纪': ['寒武纪'],
    '安路科技': ['安路'],
    '兆易创新': ['兆易创新'],
    '澜起科技': ['澜起'],
    '东威科技': ['东威'],
    '华特气体': ['华特气体'],
}

news_hits = {name: [] for name in keywords}
for title, content in recent:
    text = f"{title} {content or ''}"
    for name, kws in keywords.items():
        if any(kw in text for kw in kws):
            news_hits[name].append(title[:50])

conn.close()

# 合并
df['evidence'] = df['symbol'].map(lambda s: ev_data.get(s, 0))
df['news_7d'] = df['name'].map(lambda n: len(news_hits.get(n, [])))

# 潜力分：新闻多 * 评分 / 涨幅修正
# 新闻多=有催化，评分高=基本面好，涨幅低=还没涨
df['潜力分'] = (
    df['news_7d'] * 40 +
    df['evidence'] * 2 +
    df['score'] * 5 -
    df['ret_20d'] * 0.5
)

# 潜力股 = 近7天有新闻 + 涨幅<50% + 评分>=60
潜 = df[
    (df['news_7d'] > 0) &
    (df['ret_20d'] < 50) &
    (df['score'] >= 55)
].sort_values('潜力分', ascending=False)

print()
print('='*90)
print('  产业链热点 — 近7天新闻催化 + 股价未充分上涨')
print('='*90)
print(f'  共 {len(潜)} 只\n')
print(f'  {"代码":<8} {"名称":<8} {"细分":<12} {"评分":<5} {"20日":<9} {"新闻":<6} {"证据":<5} {"关注理由"}')
print(f'  {"-"*90}')

for _, r in 潜.head(25).iterrows():
    reason = '突破在即' if r['ret_20d'] > 15 else '低位蓄势'
    print(f"  {r['symbol']:<8} {r['name']:<8} {r['industry']:<12} {r['score']:.0f}     {r['ret_20d']:+.1f}%    {r['news_7d']:<6} {r['evidence']:<5} {reason}")

print()
print('=== 近7天产业链新闻 ===')
for name, hits in sorted(news_hits.items(), key=lambda x: -len(x[1])):
    if hits:
        unique = list(dict.fromkeys(hits))
        print(f'\n  【{name}】{len(hits)}篇')
        for h in unique[:4]:
            print(f"    → {h}")
