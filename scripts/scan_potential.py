#!/usr/bin/env python3
"""产业链潜力股扫描 — 未大涨 + RSI低位 + 横盘蓄势"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.stock_screener import scan_stocks
from data.stock_pool import SEMI_CONDUCTOR, OPTICAL_COMMS

chain_pool = {}
chain_pool.update(SEMI_CONDUCTOR)
chain_pool.update(OPTICAL_COMMS)

print(f'扫描 {len(chain_pool)} 只产业链公司...')
df = scan_stocks(chain_pool, use_cache=True)

# 潜力股：没大涨 + RSI低位 + 波动率可控 + 基本面不差
潜 = df[
    (df['ret_20d'] < 25) &
    (df['trend_strength'] < 50) &
    (df['volatility'] < 100) &
    (df['score'] >= 40)
].sort_values(['score', 'ret_20d'], ascending=[False, True])

print()
print('='*80)
print('  产业链潜力股（未大涨 + RSI低位 + 波动率可控）')
print('='*80)
print(f'  筛选出 {len(潜)} 只\n')
print(f'  {"代码":<8} {"名称":<8} {"细分":<14} {"评分":<5} {"20日涨跌":<10} {"RSI":<6} {"波动率":<6} {"关注理由"}')
print(f'  {"-"*90}')

for _, r in 潜.iterrows():
    # 判断关注理由
    if r['ret_20d'] < 5:
        reason = '低位蛰伏'
    elif r['ret_20d'] < 15:
        reason = '温和放量'
    else:
        reason = '蓄势待发'

    print(f"  {r['symbol']:<8} {r['name']:<8} {r['industry']:<14} {r['score']:.0f}     {r['ret_20d']:+.1f}%      {r['trend_strength']:.0f}     {r['volatility']:.0f}     {reason}")

# 另外扫RSI极低的超卖标的（可能反转）
print()
print('='*80)
print('  超跌反弹候选（RSI<25，短线超卖）')
print('='*80)
超跌 = df[
    (df['trend_strength'] < 25) &
    (df['volatility'] < 120) &
    (df['score'] >= 35)
].sort_values('trend_strength')

for _, r in 超跌.iterrows():
    print(f"  {r['symbol']:<8} {r['name']:<8} {r['industry']:<14} {r['score']:.0f}     {r['ret_20d']:+.1f}%      RSI={r['trend_strength']:.0f}     vol={r['volatility']:.0f}")
