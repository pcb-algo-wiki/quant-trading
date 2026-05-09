"""
数据获取模块 - 新浪财经API（稳定、免代理、支持更多历史数据）
支持:
- 股票、ETF、指数的日线/周线/月线数据
- 自动分页获取5年+历史数据
- 本地缓存+增量更新
"""

import subprocess
import json
import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
import time


DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True, parents=True)

def _get_prefix(symbol: str) -> str:
    """根据代码返回新浪/腾讯市场前缀"""
    # ETF: 51/58开头→上海, 15/16开头→深圳
    if symbol.startswith("51") or symbol.startswith("58"):
        return "sh"
    if symbol.startswith("15") or symbol.startswith("16"):
        return "sz"
    # 股票: 6开头→上海, 0/3开头→深圳, 8/4→北京
    first = symbol[0]
    if first == "6":
        return "sh"
    if first in ("0", "3"):
        return "sz"
    if first in ("8", "4"):
        return "bj"
    return "sz"  # 默认深圳


def _curl_sina(symbol: str, scale: int = 240, datalen: int = 800) -> List[dict]:
    """
    用curl获取新浪财经K线数据

    Args:
        symbol: 股票代码如 "510300"
        scale: K线周期 (240=日线, weekly=周线, monthly=月线)
        datalen: 获取条数（新浪最多2000条/次）

    Returns:
        K线字典列表 [{day, open, high, low, close, volume}, ...]
    """
    prefix = _get_prefix(symbol)
    key = f"{prefix}{symbol}"

    # 日K线: scale=240, 周K线: scale=10080, 月K线: scale=30240
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
        f"/CN_MarketData.getKLineData?symbol={key}&scale={scale}&ma=no&datalen={datalen}"
    )

    result = subprocess.run(
        ["curl", "-s", "--noproxy", "*", url],
        capture_output=True, text=True, timeout=30
    )

    text = result.stdout.strip()
    if not text or text.startswith("<?xml"):
        return []

    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _curl_tencent(symbol: str, count: int = 500) -> List[list]:
    """
    腾讯财经API（备用/辅助）
    腾讯最多500条/次，分页获取
    """
    prefix = _get_prefix(symbol)
    key = f"{prefix}{symbol}"

    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?_var=kline_dayqfq&param={key},day,,,{count},qfq"
    )

    result = subprocess.run(
        ["curl", "-s", "--noproxy", "*", url],
        capture_output=True, text=True, timeout=30
    )

    text = result.stdout.strip()
    if not text:
        return []

    try:
        import re
        json_str = re.sub(r'^[^=]+=', '', text)
        data = json.loads(json_str)
        return data["data"][key].get("qfqday", [])
    except:
        return []


def _parse_klines(klines: List[dict]) -> pd.DataFrame:
    """解析K线列表为DataFrame（新浪格式）"""
    rows = []
    for k in klines:
        if len(k) < 6:
            continue
        rows.append({
            "date": pd.to_datetime(k["day"]),
            "open": float(k["open"]),
            "close": float(k["close"]),
            "high": float(k["high"]),
            "low": float(k["low"]),
            "volume": float(k["volume"]) if k.get("volume") else 0,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _code_with_prefix(symbol: str) -> str:
    """返回带前后缀的代码"""
    prefix = _get_prefix(symbol)
    return f"{prefix}{symbol}"


def fetch_stock(
    symbol: str,
    start: str = "20190101",
    end: str = "20251231",
    force: bool = False,
) -> pd.DataFrame:
    """
    获取股票日线数据（自动分页获取完整历史）

    Args:
        symbol: 股票代码如 "000001"
        start: 开始日期 YYYYMMDD
        end: 结束日期 YYYYMMDD
        force: 强制刷新缓存
    """
    cache_file = CACHE_DIR / f"stock_{symbol}.pkl"

    # 先检查缓存
    if cache_file.exists() and not force:
        df = pd.read_pickle(cache_file)
        if len(df) > 100:
            print(f"[Cache] {symbol}: {len(df)} rows ({df['date'].min().date()} ~ {df['date'].max().date()})")
            filtered = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].copy()
            if len(filtered) > 50:
                return filtered

    print(f"[Fetch] {symbol} from {start} to {end}...")

    # 新浪API每次最多2000条，分页获取
    all_klines = []
    page = 0
    max_pages = 10  # 最多10页 = 20000条 ≈ 80年
    batch_size = 2000

    while page < max_pages:
        datalen = batch_size
        klines = _curl_sina(symbol, scale=240, datalen=datalen)
        if not klines:
            break

        all_klines = all_klines + klines  # 新浪返回升序，直接追加
        page += 1

        if len(klines) < batch_size:
            break

        if page > 1:
            print(f"  Page {page}: {len(klines)} 条, 最早 {klines[-1]['day']}")

        time.sleep(0.3)  # 避免频率限制

    if not all_klines:
        print(f"[Error] {symbol}: 无数据")
        return pd.DataFrame()

    df = _parse_klines(all_klines)

    # 过滤日期范围
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)].copy()

    # 去重：每个日期只保留第一条（有时新浪返回分钟+日线混合数据）
    df = df.drop_duplicates(subset=["date"], keep="first").reset_index(drop=True)

    if len(df) > 0:
        # 保存完整缓存
        pd.to_pickle(df, cache_file)
        print(f"[OK] {symbol}: {len(df)} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")
    else:
        print(f"[Warn] {symbol}: 无 {start}~{end} 数据")

    return df.reset_index(drop=True)


def _fetch_etf_range(symbol: str, start: str, end: str) -> pd.DataFrame:
    """直接获取ETF数据（不分页，不写缓存）"""
    all_klines = []
    page = 0
    max_pages = 10
    batch_size = 2000

    while page < max_pages:
        klines = _curl_sina(symbol, scale=240, datalen=batch_size)
        if not klines:
            break
        all_klines = all_klines + klines
        page += 1
        if len(klines) < batch_size:
            break
        time.sleep(0.3)

    if not all_klines:
        return pd.DataFrame()

    df = _parse_klines(all_klines)
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)].copy()
    return df.drop_duplicates(subset=["date"], keep="first").reset_index(drop=True)


def fetch_etf(
    symbol: str,
    start: str = "20190101",
    end: str = "20251231",
    force: bool = False,
) -> pd.DataFrame:
    """获取ETF数据（自动分页 + 增量更新）"""
    cache_file = CACHE_DIR / f"etf_{symbol}.pkl"

    if cache_file.exists() and not force:
        df = pd.read_pickle(cache_file)
        if len(df) > 100:
            cached_end = df["date"].max()
            today = pd.Timestamp.today()
            # 增量更新：缓存数据早于昨天，主动补充新数据
            if cached_end < today - pd.Timedelta(days=1):
                cache_start = cached_end.strftime("%Y%m%d")
                print(f"[Incremental] ETF {symbol} cache ends {cached_end.date()}, fetching from {cache_start}...")
                new_data = _fetch_etf_range(symbol, cache_start, today.strftime("%Y%m%d"))
                if len(new_data) > 0:
                    new_data = new_data[new_data["date"] > cached_end]
                    if len(new_data) > 0:
                        df = pd.concat([df, new_data], ignore_index=True)
                        df = df.drop_duplicates(subset=["date"], keep="first").reset_index(drop=True)
                        pd.to_pickle(df, cache_file)
                        print(f"[Updated] ETF {symbol}: {len(df)} rows ({df['date'].min().date()} ~ {df['date'].max().date()})")
            # 始终在完整缓存上过滤日期范围
            filtered = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].copy()
            if len(filtered) > 50:
                print(f"[Cache] ETF {symbol}: {len(df)} rows ({df['date'].min().date()} ~ {df['date'].max().date()})")
                return filtered

    print(f"[Fetch] ETF {symbol} from {start} to {end}...")

    all_klines = []
    page = 0
    max_pages = 10
    batch_size = 2000

    while page < max_pages:
        klines = _curl_sina(symbol, scale=240, datalen=batch_size)
        if not klines:
            break

        all_klines = all_klines + klines
        page += 1

        if len(klines) < batch_size:
            break

        time.sleep(0.3)

    if not all_klines:
        print(f"[Warn] ETF {symbol}: 无数据")
        return pd.DataFrame()

    df = _parse_klines(all_klines)

    # 过滤日期范围
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)].copy()

    # 去重：每个日期只保留第一条（有时新浪返回分钟+日线混合数据）
    df = df.drop_duplicates(subset=["date"], keep="first").reset_index(drop=True)

    if len(df) > 0:
        pd.to_pickle(df, cache_file)
        print(f"[OK] ETF {symbol}: {len(df)} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")
    else:
        print(f"[Warn] ETF {symbol}: 无 {start}~{end} 数据")

    return df.reset_index(drop=True)


def fetch_index(
    symbol: str = "000001",
    start: str = "20190101",
    end: str = "20251231",
) -> pd.DataFrame:
    """获取指数数据"""
    # 上证指数 sh000001，深证成指 sz399001
    if symbol == "000001":
        full_symbol = "sh000001"
    elif symbol == "399001":
        full_symbol = "sz399001"
    else:
        full_symbol = f"sh{symbol}"

    cache_file = CACHE_DIR / f"index_{symbol}.pkl"
    if cache_file.exists():
        df = pd.read_pickle(cache_file)
        if len(df) > 100:
            print(f"[Cache] 指数 {symbol}: {len(df)} rows")
            filtered = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].copy()
            if len(filtered) > 50:
                return filtered

    print(f"[Fetch] 指数 {symbol} from {start} to {end}...")

    klines = _curl_sina(full_symbol, scale=240, datalen=2000)
    if not klines:
        print(f"[Error] 指数 {symbol}: 无数据")
        return pd.DataFrame()

    df = _parse_klines(klines)

    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)].copy()

    if len(df) > 0:
        pd.to_pickle(df, cache_file)
        print(f"[OK] 指数 {symbol}: {len(df)} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")

    return df.reset_index(drop=True)


def fetch_batch(
    symbols: List[str],
    start: str = "20190101",
    end: str = "20241231",
    etfs: bool = False,
) -> dict:
    """批量获取多只股票/ETF"""
    results = {}
    for sym in symbols:
        try:
            if etfs:
                results[sym] = fetch_etf(sym, start, end)
            else:
                results[sym] = fetch_stock(sym, start, end)
            time.sleep(0.3)
        except Exception as e:
            print(f"[Error] {sym}: {e}")
    return results


def preload_5year_data():
    """预加载5年历史数据（2019-2024）"""
    print("\n" + "=" * 50)
    print("  预加载5年历史数据 (2019-01-01 ~ 2024-12-31)")
    print("=" * 50)

    etfs = ["510300", "510500", "159915", "512100", "159919"]  # 沪深300、中证500、创业板、纳指
    stocks = ["000001", "000002", "600519", "600036", "000858", "000333", "600276"]

    print("\n--- ETF数据 ---")
    for sym in etfs:
        fetch_etf(sym, "20190101", "20241231")

    print("\n--- 股票数据 ---")
    for sym in stocks:
        fetch_stock(sym, "20190101", "20241231")

    print("\n--- 指数数据 ---")
    fetch_index("000001", "20190101", "20241231")  # 上证
    fetch_index("399001", "20190101", "20241231")  # 深证

    print("\n[完成] 5年历史数据加载完毕")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="数据获取")
    parser.add_argument("--symbol", default="510300", help="代码")
    parser.add_argument("--start", default="20190101")
    parser.add_argument("--end", default="20241231")
    parser.add_argument("--etf", action="store_true")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--preload", action="store_true", help="预加载5年数据")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.preload:
        preload_5year_data()
    elif args.index:
        fetch_index(args.symbol, args.start, args.end)
    elif args.etf:
        fetch_etf(args.symbol, args.start, args.end, args.force)
    else:
        fetch_stock(args.symbol, args.start, args.end, args.force)
