import sys; sys.path.insert(0, '/Users/tanwei/quant-trading')
import pandas as pd
from pathlib import Path

cache = Path("data/cache")
dfs = {}
for sym in ["159915", "510500", "510300"]:
    dfs[sym] = pd.read_pickle(cache / f"etf_{sym}.pkl")

common = sorted(
    set(pd.to_datetime(dfs["159915"]["date"]).dt.date) &
    set(pd.to_datetime(dfs["510500"]["date"]).dt.date) &
    set(pd.to_datetime(dfs["510300"]["date"]).dt.date)
)

aligned = {}
for sym, df in dfs.items():
    df2 = df.copy()
    df2["d"] = pd.to_datetime(df2["date"]).dt.date
    aligned[sym] = df2[df2["d"].isin(common)].set_index("d").sort_index()

for sym in aligned:
    df2 = aligned[sym].reset_index()
    df2 = df2.rename(columns={"d": "date"})
    dupes = df2["date"].duplicated().sum()
    print(f"{sym}: {len(df2)}行, dupes={dupes}")

# 检查rotation generate里的哪一行出问题
from strategies.rotation_strategy import RotationStrategy
strat = RotationStrategy(lookback_momentum=10, rebalance_freq=5)

# 逐个ETF测试
for sym, df in aligned.items():
    df2 = df.reset_index().rename(columns={"d": "date"})
    try:
        # 模拟generate第一步
        dates = pd.to_datetime(df2["date"]).dt.date
        print(f"  {sym}: to_datetime OK, {dates.duplicated().sum()} dupes")
    except Exception as e:
        print(f"  {sym}: ERROR - {e}")
