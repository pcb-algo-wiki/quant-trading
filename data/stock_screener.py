"""
个股筛选器 v1.0
==============
基于动量 + 资金流 + 估值的综合筛选

策略逻辑:
  - 动量因子: 20日涨幅 > 0, 胜率更高
  - 趋势因子: MA20 > MA60, 趋势向上
  - 资金流: 近5日主力净流入
  - 估值: PE < 行业均值（如果能拿到）

输出:
  - 信号: Buy / Hold / Sell
  - 评分: 0-100
  - 建议仓位: 0-100%
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from typing import Optional
from data.stock_fetcher import fetch_stock_cached, get_all_stocks, SEMI_CONDUCTOR_STOCKS


def calc_momentum(df: pd.DataFrame, windows: list = [5, 20, 60]) -> pd.DataFrame:
    """计算动量指标"""
    close = df["close"]
    for w in windows:
        df[f"ret_{w}d"] = close.pct_change(w)
    # 创N日新高
    df["high_20d"] = close.rolling(20).max()
    df["near_high"] = close / df["high_20d"] - 1
    return df


def calc_trend(df: pd.DataFrame, ma_fast: int = 20, ma_slow: int = 60) -> pd.DataFrame:
    """计算趋势指标"""
    close = df["close"]
    df["ma_fast"] = close.rolling(ma_fast).mean()
    df["ma_slow"] = close.rolling(ma_slow).mean()
    df["trend_up"] = (df["ma_fast"] > df["ma_slow"]).astype(int)
    # 趋势强度
    df["trend_strength"] = (df["ma_fast"] / df["ma_slow"] - 1) * 100
    return df


def calc_volatility(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """计算波动率"""
    close = df["close"]
    df["volatility"] = close.pct_change().rolling(window).std() * np.sqrt(252)
    return df


def score_stock(df: pd.DataFrame) -> dict:
    """
    给个股打分（0-100）

    因子权重:
      - 动量(40%): 20日收益为正 + 趋势强度
      - 趋势(30%): MA20 > MA60 + 趋势稳定性
      - 近况(20%): 5日收益 + 距新高距离
      - 波动(10%): 波动率适中（太低无活力，太高风险大）
    """
    if len(df) < 60:
        return {"score": 0, "signal": "Hold", "reason": "数据不足"}

    latest = df.iloc[-1]

    # 动量得分 (0-40)
    ret_20d = latest.get("ret_20d", 0) or 0
    momentum_score = min(40, max(0, (ret_20d * 10 + 0.5) * 40))

    # 趋势得分 (0-30)
    trend_up = latest.get("trend_up", 0) or 0
    trend_strength = latest.get("trend_strength", 0) or 0
    trend_score = trend_up * 20 + min(10, max(0, trend_strength * 5))

    # 近况得分 (0-20)
    ret_5d = latest.get("ret_5d", 0) or 0
    near_high = latest.get("near_high", 0) or 0
    recent_score = min(10, max(0, ret_5d * 20)) + min(10, max(0, near_high * 10))

    # 波动得分 (0-10) — 波动率适中最好
    vol = latest.get("volatility", 0.3) or 0.3
    vol_score = 10 if 0.15 <= vol <= 0.50 else max(0, 10 - abs(vol - 0.30) * 20)

    total = momentum_score + trend_score + recent_score + vol_score

    # 信号判定
    if total >= 65 and trend_up == 1:
        signal = "Buy"
    elif total <= 35 or trend_up == 0:
        signal = "Sell"
    else:
        signal = "Hold"

    return {
        "score": round(total, 1),
        "signal": signal,
        "momentum_score": round(momentum_score, 1),
        "trend_score": round(trend_score, 1),
        "recent_score": round(recent_score, 1),
        "vol_score": round(vol_score, 1),
        "ret_20d": round(ret_20d * 100, 2) if ret_20d else 0,
        "trend_strength": round(trend_strength, 2) if trend_strength else 0,
        "volatility": round(vol * 100, 1) if vol else 0,
        "price": round(latest["close"], 2),
        "reason": _explain_signal(signal, total, trend_up, ret_20d),
    }


def _explain_signal(signal, score, trend_up, ret_20d):
    if signal == "Buy":
        return f"趋势向上(MA20>MA60) + 20日涨幅{ret_20d*100:.1f}%，综合得分{score}"
    elif signal == "Sell":
        return f"趋势向下或得分低(得分{score})，建议观望"
    else:
        return f"信号模糊，得分{score}，等待明确方向"


def analyze_stock(symbol: str, market: str, use_cache: bool = True) -> dict:
    """
    分析单只个股

    Returns:
        dict with score, signal, metrics
    """
    try:
        if use_cache:
            df = fetch_stock_cached(symbol, market)
        else:
            from data.stock_fetcher import fetch_stock
            df = fetch_stock(symbol, market)
    except Exception as e:
        return {"symbol": symbol, "market": market, "error": str(e)}

    df = calc_momentum(df)
    df = calc_trend(df)
    df = calc_volatility(df)

    result = score_stock(df)
    result["symbol"] = symbol
    result["market"] = market

    return result


def scan_stocks(stock_pool: Optional[dict] = None, use_cache: bool = True) -> pd.DataFrame:
    """
    扫描股票池，返回排名表

    Args:
        stock_pool: dict of {symbol: (market, name, sector)}
        use_cache: 是否使用缓存

    Returns:
        DataFrame sorted by score descending
    """
    if stock_pool is None:
        stock_pool = get_all_stocks()

    results = []
    for sym, info in stock_pool.items():
        mkt = info[0]
        name = info[1]
        sector = info[2] if len(info) > 2 else ""

        try:
            r = analyze_stock(sym, mkt, use_cache=use_cache)
            r["name"] = name
            r["sector"] = sector
            results.append(r)
        except Exception as e:
            results.append({
                "symbol": sym, "market": mkt, "name": name, "sector": sector,
                "score": 0, "signal": "Error", "error": str(e)
            })

    df = pd.DataFrame(results)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    return df


def format_scan_results(df: pd.DataFrame, top_n: int = 10) -> str:
    """格式化扫描结果为可读字符串"""
    lines = []
    lines.append(f"{'代码':<8} {'名称':<10} {'信号':<6} {'得分':<6} {'20日涨跌':<10} {'趋势强度':<8} {'波动率':<8}")
    lines.append("-" * 65)

    for _, row in df.head(top_n).iterrows():
        ret20 = f"{row.get('ret_20d', 0):.1f}%" if row.get('ret_20d') else "N/A"
        ts = f"{row.get('trend_strength', 0):.2f}%" if row.get('trend_strength') else "N/A"
        vol = f"{row.get('volatility', 0):.1f}%" if row.get('volatility') else "N/A"
        lines.append(
            f"{row['symbol']:<8} {row['name']:<10} {row['signal']:<6} "
            f"{row['score']:<6} {ret20:<10} {ts:<8} {vol:<8}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    import time

    # 演示：扫描半导体板块
    print("=== 半导体板块扫描 ===\n")
    df = scan_stocks(SEMI_CONDUCTOR_STOCKS, use_cache=True)
    print(format_scan_results(df, top_n=10))
