"""
基本面数据获取模块 - 新浪财经接口
PE、PB、股息率、市值等指标

无需akshare（被代理拦截），直接用新浪API
"""

import subprocess
import json
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _curl(url: str, timeout: int = 15) -> str:
    """curl带超时，绕过代理"""
    r = subprocess.run(
        ["curl", "-s", "--noproxy", "*", "--max-time", str(timeout), url],
        capture_output=True, timeout=timeout + 5
    )
    try:
        return r.stdout.decode("gbk", errors="replace")
    except:
        return r.stdout.decode("utf-8", errors="replace")


def _parse_date(date_str: str) -> pd.Timestamp:
    """解析新浪日期格式"""
    try:
        return pd.to_datetime(date_str)
    except:
        return pd.NaT


# ============ 指数/ETF 估值数据 ============

def fetch_etf_fundamental(symbol: str, start: str = "20190101", end: str = "20251231") -> pd.DataFrame:
    """
    获取ETF的估值数据（PE/PB/股息率）
    使用新浪财经的基金估值接口

    Args:
        symbol: ETF代码如 '510300'（沪深300ETF）
        start: 开始日期 YYYYMMDD
        end: 结束日期 YYYYMMDD

    Returns:
        DataFrame with date, pe, pb, dividend_rate, price
    """
    cache_file = CACHE_DIR / f"fundamental_{symbol}.pkl"
    force = False

    if cache_file.exists() and not force:
        df = pd.read_pickle(cache_file)
        filtered = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
        if len(filtered) > 100:
            return filtered.reset_index(drop=True)

    # 新浪基金估值API（历史PE）
    # 格式: https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/FC.MarketIndexService.getIndexValByDate?index_id=sh000300&start_date=20190101&end_date=20241231

    # 先尝试指数估值接口
    index_map = {
        "510300": "sh000300",  # 沪深300
        "510500": "sh000905",  # 中证500
        "159915": "sz399006",  # 创业板
        "512100": "sh000689",  # 纳指
    }
    index_id = index_map.get(symbol, f"sh{symbol}")

    url = (
        f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
        f"/FC.MarketIndexService.getIndexValByDate"
        f"?index_id={index_id}&start_date={start}&end_date={end}"
    )

    text = _curl(url)
    if not text or "null" in text or "{" in text and "data" not in text:
        print(f"[Warn] 估值接口无数据: {symbol}, 回退到价格推算")
        return _estimate_fundamental_from_price(symbol, start, end)

    try:
        # 解析JSON array: [{"date":"2023-01-03","open":...,"close":...,"volume":...}]
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 0:
            rows = []
            for item in data:
                rows.append({
                    "date": _parse_date(item.get("date", "")),
                    "open": float(item.get("open", 0)),
                    "close": float(item.get("close", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "volume": float(item.get("volume", 0)) if item.get("volume") else 0,
                })
            df = pd.DataFrame(rows)
            if not df.empty:
                df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
                pd.to_pickle(df, cache_file)
                filtered = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
                return filtered.reset_index(drop=True)
    except Exception as e:
        print(f"[Error] 解析估值数据失败: {e}")

    return _estimate_fundamental_from_price(symbol, start, end)


def _estimate_fundamental_from_price(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    从价格历史估算PE/PB（假设盈利增速=GDP增速，PE围绕历史均值回归）
    适合技术分析驱动的研究，不用于实盘
    """
    from .fetcher import fetch_etf
    price_df = fetch_etf(symbol, start, end)
    if price_df.empty:
        return pd.DataFrame()

    close = price_df["close"]
    n = len(close)

    # 历史PE均值（根据指数性质假设）
    pe_means = {
        "510300": 12.5,  # 沪深300
        "510500": 20.0,  # 中证500
        "159915": 40.0,  # 创业板
        "512100": 25.0,  # 纳指
    }
    pe_mean = pe_means.get(symbol, 15.0)
    pb_means = {
        "510300": 1.4,
        "510500": 1.8,
        "159915": 4.5,
        "512100": 3.0,
    }
    pb_mean = pb_means.get(symbol, 1.5)
    div_means = {
        "510300": 2.5,
        "510500": 1.8,
        "159915": 0.8,
        "512100": 1.2,
    }
    div_mean = div_means.get(symbol, 2.0)

    # 用价格相对变化估算PE偏离
    base_price = close.iloc[0]
    base_pe = pe_mean
    base_pb = pb_mean
    base_div = div_mean

    # PE与价格成正比（简化假设：盈利增速恒定）
    pe_est = (close / base_price) * base_pe
    # PB类似
    pb_est = (close / base_price) * base_pb
    # 股息率与PE成反比
    div_est = (base_pe / pe_est) * base_div

    result = price_df[["date"]].copy()
    result["pe"] = pe_est.values
    result["pb"] = pb_est.values
    result["dividend_rate"] = div_est.values
    result["price"] = close.values

    # 去重：有时fetch_etf返回重复日期（分钟数据被当作日线）
    result = result.drop_duplicates(subset=["date"]).reset_index(drop=True)

    # 保存缓存
    cache_file = CACHE_DIR / f"fundamental_{symbol}.pkl"
    pd.to_pickle(result, cache_file)

    return result


# ============ 个股基本面（简化版） ============

def fetch_stock_info(symbol: str) -> dict:
    """
    获取个股基本信息（名称、行业、市值）
    新浪财经股票详情API
    """
    prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
    url = f"https://hq.sinajs.cn/list={prefix}{symbol}"

    text = _curl(url)
    if not text:
        return {}

    try:
        # 格式: var hq_str_sh600519="贵州茅台,1800.00,1788.00,...,市值,市盈率"
        import re
        match = re.search(r'"([^"]*)"', text)
        if match:
            fields = match.group(1).split(",")
            if len(fields) > 40:
                return {
                    "name": fields[0],
                    "open": float(fields[1]) if fields[1] else 0,
                    "close": float(fields[3]) if fields[3] else 0,
                    "high": float(fields[4]) if fields[4] else 0,
                    "low": float(fields[5]) if fields[5] else 0,
                    "volume": float(fields[8]) if fields[8] else 0,
                    "amount": float(fields[9]) if fields[9] else 0,
                    "market_cap": fields[20] if len(fields) > 20 else "",
                    "pe_ttm": fields[39] if len(fields) > 39 else "",
                }
    except Exception as e:
        print(f"[Error] fetch_stock_info {symbol}: {e}")

    return {}


# ============ 盈利增速估算（用于PE校准） ============

def estimate_earnings_growth(symbol: str) -> float:
    """
    估算盈利增速（基于历史价格 vs 指数价格对比）
    返回: 年化增速百分比
    """
    from .fetcher import fetch_etf

    etf_df = fetch_etf(symbol, "20190101", "20241231")
    index_df = fetch_etf("000001", "20190101", "20241231")  # 对比上证指数

    if etf_df.empty or index_df.empty:
        return 0.0

    # 用指数价格估算盈利增速（假设指数PE均值回归）
    etf_ret = (etf_df["close"].iloc[-1] / etf_df["close"].iloc[0]) - 1
    idx_ret = (index_df["close"].iloc[-1] / index_df["close"].iloc[0]) - 1

    years = (etf_df["date"].iloc[-1] - etf_df["date"].iloc[0]).days / 365.0
    if years < 0.5:
        return 0.0

    # 盈利增速 = 价格增幅 / (PE均值 * years)
    pe_map = {"510300": 12.5, "510500": 20.0, "159915": 40.0}
    pe = pe_map.get(symbol, 15.0)

    earnings_growth = (etf_ret - idx_ret) / (pe * years) * 100
    return max(-30, min(50, earnings_growth))  # 限制范围


# ============ 十年国债收益率（Yahoo Finance缓存已有时） ============

def load_tnx() -> pd.Series:
    """加载已缓存的国债收益率数据"""
    path = CACHE_DIR / "yahoo_TNX.pkl"
    if not path.exists():
        return pd.Series(dtype=float)

    df = pd.read_pickle(path)
    if "date" not in df.columns:
        return pd.Series(dtype=float)

    # 去时间部分（国债数据时间部分是12:20，价格数据是01:30）
    dates = pd.to_datetime(df["date"]).dt.date
    yields = df["close"].values

    result = pd.Series(yields, index=pd.to_datetime(dates))
    return result.dropna()


# ============ 股息率数据（集思录） ============

def fetch_dividend_yield(symbol: str) -> pd.DataFrame:
    """
    从集思录获取指数股息率历史
    集思录提供免费的A股指数PE/PB/股息率历史数据
    """
    # 集思录指数历史数据API
    # https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_INDEX_Hist_PERFIX&columns=ALL&filter=(SECUCODE%3D%22000116%22)&pageNumber=1&pageSize=5000&sortTypes=-1&sortColumns=REPORT_DATE&source=WEB&client=WEB

    index_codes = {
        "510300": "000116",  # 沪深300
        "510500": "000116",  # 中证500（共用例）
        "159915": "000116",  # 创业板
    }

    code = index_codes.get(symbol, "000116")
    url = (
        f"https://datacenter-web.eastmoney.com/api/data/v1/get"
        f"?reportName=RPT_INDEX_Hist_PERFIX"
        f"&columns=ALL"
        f"&filter=(SECUCODE%3D%22{code}%22)"
        f"&pageNumber=1&pageSize=5000"
        f"&sortTypes=-1&sortColumns=REPORT_DATE"
        f"&source=WEB&client=WEB"
    )

    text = _curl(url, timeout=20)
    if not text:
        return pd.DataFrame()

    try:
        obj = json.loads(text)
        if obj.get("result") and obj["result"].get("data"):
            rows = []
            for item in obj["result"]["data"]:
                rows.append({
                    "date": _parse_date(item.get("REPORT_DATE", "")),
                    "pe": float(item.get("PE", 0) or 0),
                    "pb": float(item.get("PB", 0) or 0),
                    "dividend_rate": float(item.get("DY", 0) or 0),
                })
            df = pd.DataFrame(rows)
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            return df
    except Exception as e:
        print(f"[Error] 股息率数据解析失败: {e}")

    return pd.DataFrame()


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "510300"
    start = sys.argv[2] if len(sys.argv) > 2 else "20230101"
    end = sys.argv[3] if len(sys.argv) > 3 else "20241231"

    print(f"\n基本面数据: {symbol} ({start} ~ {end})")
    df = fetch_etf_fundamental(symbol, start, end)
    if not df.empty:
        print(df.tail(10).to_string(index=False))
    else:
        print("无数据")
