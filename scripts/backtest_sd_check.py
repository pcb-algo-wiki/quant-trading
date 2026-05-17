#!/usr/bin/env python3
"""检查数据可用性"""
import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")

import pandas as pd
from pathlib import Path

cached = set(p.stem for p in Path("data/cache/stocks").glob("*.pkl"))
print("缓存股票数:", len(cached))

from data.stock_pool import ALL_STOCKS
pool_codes = set(ALL_STOCKS.keys())
overlap = pool_codes & cached
print("股票池总数:", len(pool_codes))
print("有缓存的股票池股票:", len(overlap))
print("Overlap samples:", sorted(overlap)[:10])

# ETF
for sym in ["159915", "510300", "510500", "512100"]:
    p = Path(f"data/cache/etf_{sym}.pkl")
    if p.exists():
        df = pd.read_pickle(p)
        print(f"ETF {sym}: {len(df)}行, {df['date'].min()} ~ {df['date'].max()}")

# 检查哪些segment有对应股票在缓存中
from knowledge.supply_chain import get_stock_by_segment, get_all_chain_segments
from data.stock_pool import ALL_STOCKS

all_segs = get_all_chain_segments()
for seg in all_segs:
    stocks = get_stock_by_segment(seg)
    has_data = [s for s in stocks if s[0] in cached]
    if has_data:
        print(f"  {seg}: {len(has_data)}/{len(stocks)} 只有缓存数据")
