"""
数据获取模块 - 腾讯财经API（稳定、免代理）
"""

import subprocess
import json
import re
import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List


DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True, parents=True)

# 腾讯财经前缀: sh=上证, sz=深证
PREFIX_MAP = {"0": "sz", "6": "sh", "8": "bj", "4": "bj"}


def _get_prefix(symbol: str) -> str:
    """根据代码返回腾讯市场前缀"""
    first = symbol[0]
    return PREFIX_MAP.get(first, "sz")


def _curl_tencent(symbol: str, count: int = 500) -> List[list]:
    """
    用curl获取腾讯财经K线数据

    Args:
        symbol: 股票代码如 "000001"
        count: 获取条数

    Returns:
        K线列表 [[date, open, close, high, low, volume], ...]
    """
    prefix = _get_prefix(symbol)
    key = f"{prefix}{symbol}"

    # 注意：腾讯API每次最多500条
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

    # 解析 JSONP: kline_dayqfq={...}
    try:
        json_str = re.sub(r'^[^=]+=', '', text)
        data = json.loads(json_str)
        klines = data["data"][key].get("qfqday", [])
        return klines
    except (json.JSONDecodeError, KeyError) as e:
        return []


def _parse_klines(klines: List[list]) -> pd.DataFrame:
    """解析K线列表为DataFrame"""
    rows = []
    for k in klines:
        if len(k) < 6:
            continue
        rows.append({
            "date": pd.to_datetime(k[0]),
            "open": float(k[1]),
            "close": float(k[2]),
            "high": float(k[3]),
            "low": float(k[4]),
            "volume": float(k[5]),
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
    start: str = "20200101",
    end: str = "20251231",
    force: bool = False,
    max_bars: int = 800,
) -> pd.DataFrame:
    """
    获取股票日线数据（合并多次请求覆盖全周期）

    Args:
        symbol: 股票代码如 "000001"
        start: 开始日期 YYYYMMDD
        end: 结束日期 YYYYMMDD
        force: 强制刷新缓存
        max_bars: 最大获取条数（腾讯每次最多500）
    """
    cache_file = CACHE_DIR / f"stock_{symbol}.pkl"

    if cache_file.exists() and not force:
        df = pd.read_pickle(cache_file)
        df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].copy()
        if len(df) > 50:
            print(f"[Cache] {symbol}: {len(df)} rows")
            return df

    print(f"[Fetch] {symbol} from {start} to {end}...")

    # 腾讯每次最多500条，分多次请求
    all_klines = []
    remaining = max_bars
    page = 1

    while remaining > 0:
        count = min(500, remaining)
        klines = _curl_tencent(symbol, count=count)
        if not klines:
            break

        all_klines = klines + all_klines  # 腾讯返回是倒序，合并时反转
        remaining -= count
        page += 1

        if len(klines) < 500:
            break

    if not all_klines:
        print(f"[Error] {symbol}: 无数据")
        return pd.DataFrame()

    df = _parse_klines(all_klines)

    # 过滤日期范围
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

    if len(df) > 0:
        # 缓存全部数据（不含日期过滤）
        full_cache = CACHE_DIR / f"stock_{symbol}_full.pkl"
        pd.read_pickle(full_cache) if full_cache.exists() else None
        pd.to_pickle(df, cache_file)
        print(f"[OK] {symbol}: {len(df)} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")
    else:
        print(f"[Warn] {symbol}: 无 {start}~{end} 数据")

    return df.reset_index(drop=True)


def fetch_etf(
    symbol: str,
    start: str = "20200101",
    end: str = "20251231",
    force: bool = False,
) -> pd.DataFrame:
    """获取ETF数据（ETF在上海市场用sh前缀）"""
    # ETF多是上海交易所，代码51开头用sh
    if symbol.startswith("51") or symbol.startswith("15"):
        prefix = "sh"
    else:
        prefix = "sz"

    cache_file = CACHE_DIR / f"etf_{symbol}.pkl"

    if cache_file.exists() and not force:
        df = pd.read_pickle(cache_file)
        if len(df) > 10:
            print(f"[Cache] ETF {symbol}: {len(df)} rows")
            if start != "20200101" or end != "20251231":
                filtered = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))].copy()
                return filtered if len(filtered) > 10 else pd.DataFrame()
            return df.copy()
        return pd.DataFrame()
    print(f"[Fetch] ETF {symbol} from {start} to {end}...")

    all_klines = []
    remaining = 800
    while remaining > 0:
        count = min(500, remaining)
        key = f"{prefix}{symbol}"
        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?_var=kline_dayqfq&param={key},day,,,{count},qfq"
        )
        result = subprocess.run(
            ["curl", "-s", url],
            capture_output=True, text=True, timeout=30
        )
        text = result.stdout.strip()
        if not text:
            break
        try:
            json_str = re.sub(r'^[^=]+=', '', text)
            data = json.loads(json_str)
            # 尝试多个key
            klines = data["data"][key].get("qfqday", [])
            if not klines:
                klines = data["data"][key].get("day", [])
        except:
            break

        if not klines:
            break

        all_klines = klines + all_klines
        remaining -= count
        if len(klines) < 500:
            break

    if not all_klines:
        print(f"[Warn] ETF {symbol}: 无数据")
        return pd.DataFrame()

    df = _parse_klines(all_klines)
    if len(df) == 0:
        return pd.DataFrame()

    # 保存原始完整数据
    pd.to_pickle(df, cache_file)

    # 返回过滤后的数据
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

    print(f"[OK] ETF {symbol}: {len(df)} rows")
    return df.reset_index(drop=True)


def fetch_index(
    symbol: str = "000001",
    start: str = "20200101",
    end: str = "20251231",
) -> pd.DataFrame:
    """获取指数数据"""
    # 上证指数 sh000001，深证成指 sz399001
    if symbol == "000001":
        key = "sh000001"
    elif symbol == "399001":
        key = "sz399001"
    else:
        key = f"sh{symbol}"

    cache_file = CACHE_DIR / f"index_{symbol}.pkl"
    if cache_file.exists():
        df = pd.read_pickle(cache_file)
        df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
        if len(df) > 50:
            return df

    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?_var=kline_dayqfq&param={key},day,,,800,qfq"
    )
    result = subprocess.run(
        ["curl", "-s", "--noproxy", "*", url],
        capture_output=True, text=True, timeout=30
    )
    text = result.stdout.strip()
    try:
        json_str = re.sub(r'^[^=]+=', '', text)
        data = json.loads(json_str)
        klines = data["data"][key].get("qfqday", [])
    except:
        return pd.DataFrame()

    df = _parse_klines(klines)
    if len(df) > 0:
        pd.to_pickle(df, cache_file)
    return df.reset_index(drop=True)


def fetch_batch(
    symbols: List[str],
    start: str = "20230101",
    end: str = "20241231",
) -> dict:
    """批量获取多只股票"""
    results = {}
    for sym in symbols:
        try:
            results[sym] = fetch_stock(sym, start, end)
        except Exception as e:
            print(f"[Error] {sym}: {e}")
    return results


if __name__ == "__main__":
    # 测试
    print("测试腾讯财经API数据获取...")
    df = fetch_stock("000001", "20230101", "20241231")
    print(f"获取 {len(df)} 条数据")
    if len(df) > 0:
        print(df.tail(3))
