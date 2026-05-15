"""
美股数据获取模块 - Yahoo Finance
支持: SPY, QQQ, IWM, VIX, TNX 及个股
数据从2019-01-01开始，存到 cache/ 目录，pkl格式
"""

import subprocess
import json
import os
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional

# 添加项目根目录到路径
DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True, parents=True)

# 虚拟环境中的Python路径
VENV_PYTHON = Path(__file__).parent.parent / ".venv" / "bin" / "python3"


def _check_yfinance() -> bool:
    """检查yfinance是否可用"""
    result = subprocess.run(
        [str(VENV_PYTHON), "-c", "import yfinance"],
        capture_output=True, text=True
    )
    return result.returncode == 0


def _run_yfinance_script(script: str) -> str:
    """在虚拟环境中运行Python脚本（绕过代理）"""
    result = subprocess.run(
        [str(VENV_PYTHON), "-c", script],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": ""}
    )
    if result.returncode != 0:
        raise RuntimeError(f"yfinance fetch failed: {result.stderr}")
    return result.stdout.strip()


def _fetch_yahoo_data(ticker: str, start: str = "2019-01-01", end: str = "2026-12-31") -> pd.DataFrame:
    """
    用yfinance获取单个标的数据
    
    Args:
        ticker: Yahoo代码，如 'SPY', '^VIX', '^TNX'
        start: 开始日期
        end: 结束日期
    
    Returns:
        DataFrame with date, open, high, low, close, volume, adj_close
    """
    script = f"""
import yfinance as yf
import pandas as pd
import json

ticker = yf.Ticker("{ticker}")
df = ticker.history(start="{start}", end="{end}", auto_adjust=False)

if df.empty:
    print("EMPTY")
else:
    df = df.reset_index()
    # 处理时区：转为UTC然后去掉时区信息
    if df['Date'].dt.tz is not None:
        df['Date'] = df['Date'].dt.tz_convert('UTC').dt.tz_localize(None)
    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    print(df.to_json(orient='records'))
"""
    output = _run_yfinance_script(script)
    
    if output == "EMPTY" or not output.strip():
        print(f"[Warn] {ticker}: 无数据")
        return pd.DataFrame()
    
    try:
        records = json.loads(output)
    except json.JSONDecodeError:
        print(f"[Error] {ticker}: JSON解析失败")
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    
    # 标准化列名
    col_map = {
        'Date': 'date',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume',
        'Adj Close': 'adj_close',
    }
    df = df.rename(columns=col_map)
    
    # 确保有date列
    if 'date' not in df.columns:
        print(f"[Error] {ticker}: 无date列，列名: {df.columns.tolist()}")
        return pd.DataFrame()
    
    # 保留必要列
    keep_cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'adj_close']
    df = df[[c for c in keep_cols if c in df.columns]]
    
    # 转换日期
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    
    # 转换数值
    for col in ['open', 'high', 'low', 'close', 'volume', 'adj_close']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.dropna().sort_values('date').reset_index(drop=True)
    
    print(f"[OK] {ticker}: {len(df)} rows, {df['date'].min().date()} ~ {df['date'].max().date()}")
    return df


def fetch_us_etf(
    ticker: str,
    start: str = "2019-01-01",
    end: str = "2026-12-31",
    force: bool = False,
) -> pd.DataFrame:
    """
    获取美股ETF/指数数据
    
    Args:
        ticker: 'SPY', 'QQQ', 'IWM', '^VIX', '^TNX'
        start: 开始日期
        end: 结束日期
        force: 强制刷新缓存
    
    Returns:
        DataFrame with date, open, high, low, close, volume, adj_close
    """
    cache_file = CACHE_DIR / f"yahoo_{ticker.replace('^', '')}.pkl"
    
    # 检查缓存
    if cache_file.exists() and not force:
        df_cached = pd.read_pickle(cache_file)
        if len(df_cached) > 100:
            print(f"[Cache] {ticker}: {len(df_cached)} rows ({df_cached['date'].min().date()} ~ {df_cached['date'].max().date()})")
            filtered = df_cached[(df_cached['date'] >= pd.to_datetime(start)) & (df_cached['date'] <= pd.to_datetime(end))].copy()
            if len(filtered) > 50:
                return filtered
    
    if not _check_yfinance():
        print("[Error] yfinance not available, trying install...")
        install_result = subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "yfinance", "-q"],
            capture_output=True, text=True, timeout=60
        )
        if install_result.returncode != 0:
            print(f"[Error] yfinance install failed: {install_result.stderr.decode()}")
            return pd.DataFrame()
    
    print(f"[Fetch] {ticker} from {start} to {end}...")
    df = _fetch_yahoo_data(ticker, start, end)
    
    if df.empty:
        return df
    
    # 保存完整缓存
    pd.to_pickle(df, cache_file)
    print(f"[Saved] {ticker} -> {cache_file.name}")
    
    # 返回过滤后的数据
    filtered = df[(df['date'] >= pd.to_datetime(start)) & (df['date'] <= pd.to_datetime(end))].copy()
    return filtered.reset_index(drop=True)


def fetch_all_us_data(
    start: str = "2019-01-01",
    end: str = "2026-12-31",
    force: bool = False,
) -> dict:
    """
    获取所有美股数据 (SPY, QQQ, IWM, VIX, TNX)
    
    Returns:
        dict: {ticker: DataFrame}
    """
    tickers = {
        'SPY': 'SPY',   # S&P 500 ETF
        'QQQ': 'QQQ',   # Nasdaq 100 ETF
        'IWM': 'IWM',   # Russell 2000 ETF
        'VIX': '^VIX',  # Volatility Index
        'TNX': '^TNX',  # 10-Year Treasury Yield
    }
    
    results = {}
    for name, ticker in tickers.items():
        df = fetch_us_etf(ticker, start, end, force=force)
        if not df.empty:
            results[name] = df
        # 避免请求过快
        import time
        time.sleep(0.5)
    
    return results


def load_us_data(
    tickers: list = None,
    start: str = "2019-01-01",
    end: str = "2026-12-31",
) -> dict:
    """
    加载美股数据（从缓存）
    
    Args:
        tickers: 要加载的标的列表，如 ['SPY', 'QQQ', 'IWM']
        start/end: 日期范围过滤
    
    Returns:
        dict: {ticker: DataFrame}
    """
    if tickers is None:
        tickers = ['SPY', 'QQQ', 'IWM', 'VIX', 'TNX']
    
    results = {}
    for t in tickers:
        cache_file = CACHE_DIR / f"yahoo_{t.replace('^', '')}.pkl"
        if cache_file.exists():
            df = pd.read_pickle(cache_file)
            filtered = df[(df['date'] >= pd.to_datetime(start)) & (df['date'] <= pd.to_datetime(end))].copy()
            results[t] = filtered
        else:
            print(f"[Warn] {t} not found in cache, run fetch_all_us_data() first")
    
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="美股数据获取")
    parser.add_argument("--ticker", default="SPY", help="标的代码: SPY, QQQ, IWM, VIX, TNX")
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2026-12-31")
    parser.add_argument("--all", action="store_true", help="获取所有美股数据")
    parser.add_argument("--force", action="store_true", help="强制刷新")
    args = parser.parse_args()
    
    if args.all:
        print("Fetching all US stock data (SPY, QQQ, IWM, VIX, TNX)...")
        fetch_all_us_data(args.start, args.end, force=args.force)
    else:
        ticker_map = {'VIX': '^VIX', 'TNX': '^TNX'}
        ticker = ticker_map.get(args.ticker, args.ticker)
        fetch_us_etf(ticker, args.start, args.end, force=args.force)
