"""
多空对冲策略回测
用法: python scripts/test_long_short.py
"""
import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")

import pandas as pd
import numpy as np
from pathlib import Path
from strategies.long_short import LongShortStrategy


def load_stock_data():
    """加载个股+ETF数据"""
    cache_dir = Path("/Users/tanwei/quant-trading/data/cache/stocks")
    etf_cache = Path("/Users/tanwei/quant-trading/data/cache")
    records = []
    for fname in ["etf_159915.pkl", "etf_510500.pkl", "etf_510300.pkl"]:
        fpath = etf_cache / fname
        if fpath.exists():
            df = pd.read_pickle(fpath).reset_index()
            if "date" in df.columns:
                df["code"] = fname.replace("etf_", "").replace(".pkl", "")
                records.append(df[["date", "code", "open", "high", "low", "close", "volume"]])
    for fpath in cache_dir.glob("*.pkl"):
        try:
            df = pd.read_pickle(fpath)
            if len(df) > 0:
                df = df.reset_index()
                if "date" in df.columns:
                    df["code"] = fpath.stem.replace("stock_", "")
                    records.append(df[["date", "code", "open", "high", "low", "close", "volume"]])
        except Exception:
            continue
    if not records:
        return pd.DataFrame()
    combined = pd.concat(records, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.drop_duplicates(subset=["date", "code"]).sort_values(["date", "code"])
    combined = combined.set_index(["date", "code"])
    return combined


def summarize(result, label):
    if len(result) == 0:
        print(f"\n{label}: 无数据")
        return
    equity = result["equity"]
    returns = result["returns"]
    total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    years = (result["date"].iloc[-1] - result["date"].iloc[0]).days / 365.25
    annual_return = ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
    annual_vol = returns.std() * np.sqrt(252) * 100
    sharpe = (annual_return / annual_vol) if annual_vol > 0 else 0
    max_dd = ((equity / equity.cummax()) - 1).min() * 100
    print(f"\n{label}")
    print(f"  区间: {result['date'].iloc[0].date()} ~ {result['date'].iloc[-1].date()}")
    print(f"  总收益: {total_return:.1f}%")
    print(f"  年化收益: {annual_return:.1f}%")
    print(f"  年化波动: {annual_vol:.1f}%")
    print(f"  夏普比率: {sharpe:.2f}")
    print(f"  最大回撤: {max_dd:.1f}%")
    print(f"  最终权益: {equity.iloc[-1]:,.0f}")


def main():
    print("=" * 60)
    print("多空对冲策略 (Long-Short Equity) 回测")
    print("=" * 60)

    data = load_stock_data()
    print(f"\n数据范围: {data.index.get_level_values('date').min().date()} ~ "
          f"{data.index.get_level_values('date').max().date()}")
    print(f"总记录: {len(data):,}")
    print(f"股票数: {data.index.get_level_values('code').nunique()}")

    # 排除ETF，只用个股
    stock_codes = [c for c in data.index.get_level_values("code").unique()
                   if not c.startswith("51") and not c.startswith("15")]
    stock_data = data[data.index.get_level_values("code").isin(stock_codes)]
    print(f"个股数: {len(stock_codes)}")

    # ===== 参数扫描 =====
    configs = [
        # 单边做多（短期动量）
        {"lookback": 10, "top_n": 20, "short_n": 0, "rebalance_days": 7,  "label": "做多Top20 动量10日 7天调仓"},
        {"lookback": 20, "top_n": 20, "short_n": 0, "rebalance_days": 14, "label": "做多Top20 动量20日 双周调仓"},
        {"lookback": 20, "top_n": 30, "short_n": 0, "rebalance_days": 14, "label": "做多Top30 动量20日 双周调仓"},
        # 多空对冲（需要足够数据才有效）
        {"lookback": 20, "top_n": 20, "short_n": 10, "rebalance_days": 14, "label": "多空Top20/Short10 双周调仓"},
    ]

    # 对比基准
    close_300 = data.xs("510300", level="code")["close"] if "510300" in data.index.get_level_values("code") else None

    for cfg in configs:
        strategy = LongShortStrategy(
            lookback=cfg["lookback"],
            top_pct=0.2,
            bottom_pct=0.2,
            hedge_ratio=0.0,  # 暂不对冲，简化测试
            index_etf="510300",
            min_stocks=10,
        )
        result = strategy.backtest(
            stock_data,
            initial_capital=100000.0,
            rebalance_days=cfg["rebalance_days"],
            top_n=cfg["top_n"],
            short_n=cfg["short_n"],
        )
        summarize(result, cfg["label"])

        if len(result) > 0 and close_300 is not None:
            start, end = result["date"].iloc[0], result["date"].iloc[-1]
            hs300_equiv = close_300.loc[start:end]
            if len(hs300_equiv) > 1:
                bh = (hs300_equiv.iloc[-1] / hs300_equiv.iloc[0] - 1) * 100
                alpha = (result["equity"].iloc[-1] / result["equity"].iloc[0] - 1) * 100 - bh
                print(f"  对比沪深300 BH: {bh:.1f}%, 超额: {alpha:.1f}%")


if __name__ == "__main__":
    main()
