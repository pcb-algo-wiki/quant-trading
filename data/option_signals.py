"""
期权情绪数据模块
数据来源: akshare option_daily_stats_sse (上交所每日统计)
- PCR (Put/Call Ratio) 认沽认购比
- 成交额/成交量对比
- 隐波偏离度 (基于收盘价反推)

使用方式:
    from data.option_signals import get_pcr_signals, get_greeks
    signals = get_pcr_signals()     # 当日PCR情绪
    greeks = get_greeks('io2606')  # 特定合约Greeks
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import subprocess, json, sys

# ─── PCR情绪 ────────────────────────────────────────────────────────────────

def get_pcr_signals(date: Optional[str] = None) -> pd.DataFrame:
    """
    获取上交所期权每日统计（PCR情绪信号）

    Args:
        date: 交易日，格式YYYYMMDD，默认最新

    Returns:
        DataFrame[ETF代码, ETF名称, PCR, 成交额, 信号]
        信号: extreme_bullish(<0.7) / bearish(>1.2) / neutral
    """
    import akshare as ak

    if date is None:
        date = datetime.now().strftime('%Y%m%d')

    try:
        df = ak.option_daily_stats_sse(date=date)
    except Exception as e:
        print(f"[PCR] 获取失败 {date}: {e}")
        return pd.DataFrame()

    # 容错：周末/节假日返回异常格式时返回空
    if df.empty or '合约标的代码' not in df.columns:
        return pd.DataFrame()

    # 过滤ETF期权
    df = df[df['合约标的代码'].astype(str).str.startswith(('510', '588'))].copy()

    if df.empty:
        return pd.DataFrame()

    # 先用原始列名计算（rename之后列名会变）
    # 计算正确PCR（成交量口径） + OI_PCR（持仓量口径）
    df['vol_pcr'] = df['认沽成交量'] / df['认购成交量'].replace(0, float('nan'))
    df['oi_pcr'] = df['未平仓认沽合约数'] / df['未平仓认购合约数'].replace(0, float('nan'))
    df['turnover'] = df['总成交额'].astype(float) / 1e4  # 万元→万

    # 情绪信号（基于成交量PCR）
    def sentiment(pcr):
        if pd.isna(pcr):
            return 'neutral'
        if pcr < 0.75:
            return 'extreme_bullish'
        if pcr > 1.25:
            return 'bearish'
        if pcr < 0.90:
            return 'bullish'
        if pcr > 1.10:
            return 'bearish'
        return 'neutral'

    df['signal'] = df['vol_pcr'].apply(sentiment)
    df['date'] = date

    # 重命名（保留计算列）
    df = df.rename(columns={
        '合约标的代码': 'code',
        '合约标的名称': 'name',
        '认沽/认购': 'pcr_display',
    })

    return df[['date', 'code', 'name', 'turnover', 'vol_pcr', 'oi_pcr', 'pcr_display', 'signal']]


def get_pcr_history(days: int = 20) -> pd.DataFrame:
    """
    获取最近N个交易日的PCR历史

    Args:
        days: 历史天数（会去重，实际交易日略少）

    Returns:
        DataFrame[date, code, name, turnover, pcr, signal]
    """
    records = []
    today = datetime.now()
    # 从今天往前扫，最多2倍天数（考虑周末）
    for i in range(days * 2):
        d = today - timedelta(days=i)
        date_str = d.strftime('%Y%m%d')
        try:
            df = get_pcr_signals(date_str)
            if not df.empty:
                records.append(df)
        except Exception:
            pass
        if len(records) >= days:
            break

    if not records:
        return pd.DataFrame()

    result = pd.concat(records, ignore_index=True)
    result = result.drop_duplicates(subset=['date', 'code'])
    result = result.sort_values(['date', 'pcr']).reset_index(drop=True)
    return result


def get_pcr_signal_510300() -> Dict:
    """
    沪深300ETF(510300)专项PCR信号，用于择时

    Returns:
        dict: {pcr, signal, signal_score, interpretation}
        signal_score: -2(极度看空) ~ +2(极度看多)
    """
    # 尝试最近5个交易日
    from datetime import timedelta
    for days_back in range(1, 8):
        d = datetime.now() - timedelta(days=days_back)
        date_str = d.strftime('%Y%m%d')
        df = get_pcr_signals(date_str)
        if df.empty:
            continue
        row = df[df['code'] == '510300']
        if row.empty:
            continue
        pcr = float(row['vol_pcr'].iloc[0])
        signal = row['signal'].iloc[0]

    # 细分信号评分
    score = 0
    if pcr < 0.5:
        score = 2
        interp = '极度看多（恐慌抄底信号）'
    elif pcr < 0.75:
        score = 1
        interp = '偏多（散户看空，反向指标）'
    elif pcr < 0.90:
        score = 0
        interp = '略偏多'
    elif pcr < 1.10:
        score = 0
        interp = '中性'
    elif pcr < 1.25:
        score = -1
        interp = '偏空（乐观情绪，注意回调风险）'
    else:
        score = -2
        interp = '极度看空（散户疯狂看多，可能顶部）'

    return {
        'code': '510300',
        'pcr': round(pcr, 3),
        'oi_pcr': round(float(row['oi_pcr'].iloc[0]), 3),
        'signal': signal,
        'signal_score': score,
        'interpretation': interp,
    }


# ─── Greeks实时行情 ──────────────────────────────────────────────────────────

def get_greeks(contract: str = 'io2606') -> pd.DataFrame:
    """
    获取沪深300指数期权的实时Greeks

    Args:
        contract: 合约代码，如 'io2606'（当月）/ 'io2609'（季月）

    Returns:
        DataFrame: [strike, call_price, put_price, call_iv, put_iv,
                    delta, gamma, theta, vega]
    """
    import akshare as ak

    try:
        df = ak.option_cffex_hs300_spot_sina(symbol=contract)
    except Exception as e:
        print(f"[Greeks] 获取失败 {contract}: {e}")
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    return df


def compute_iv_row(row: pd.Series, S: float, r: float = 0.03, T: float = 30/365) -> dict:
    """
    用Black-Scholes反推隐含波动率（简化版，无scipy时用二分法）

    注意: 此函数依赖scipy，未安装时返回NaN
    """
    try:
        from scipy.stats import norm
    except ImportError:
        return {'call_iv': None, 'put_iv': None}

    K = float(row['行权价'])
    C = float(row.get('看涨合约-最新价', 0))
    P = float(row.get('看跌合约-最新价', 0))

    def bs_iv(price, K, T, r, is_call=True):
        """二分法求IV"""
        low, high = 0.001, 5.0
        for _ in range(100):
            mid = (low + high) / 2
            d1 = (math.log(S / K) + (r + mid**2/2) * T) / (mid * math.sqrt(T))
            d2 = d1 - mid * math.sqrt(T)
            if is_call:
                p = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            else:
                p = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            if abs(p - price) < 1e-6:
                break
            if p < price:
                low = mid
            else:
                high = mid
        return mid

    import math
    call_iv = bs_iv(C, K, T, r, True) if C > 0 else None
    put_iv = bs_iv(P, K, T, r, False) if P > 0 else None

    return {'call_iv': call_iv, 'put_iv': put_iv}


def get_iv_smile(contract: str = 'io2606', S: Optional[float] = None) -> pd.DataFrame:
    """
    获取完整IV Smile（波动率微笑曲线）

    Returns:
        DataFrame: [strike, call_price, put_price, call_iv, put_iv, iv_diff]
        iv_diff = put_iv - call_iv（正常市场>0）
    """
    df = get_greeks(contract)
    if df.empty:
        return pd.DataFrame()

    if S is None:
        S = float(df[df['看涨合约-标识'] == contract]['看涨合约-买价'].iloc[0]) if len(df) > 0 else 3500

    results = []
    for _, row in df.iterrows():
        try:
            iv = compute_iv_row(row, S)
            r = {
                'strike': float(row['行权价']),
                'call_price': float(row.get('看涨合约-最新价', 0)),
                'put_price': float(row.get('看跌合约-最新价', 0)),
                'call_iv': iv['call_iv'],
                'put_iv': iv['put_iv'],
            }
            if r['call_iv'] and r['put_iv']:
                r['iv_diff'] = r['put_iv'] - r['call_iv']
            else:
                r['iv_diff'] = None
            results.append(r)
        except Exception:
            pass

    return pd.DataFrame(results)


# ─── 期权波动率预警 ───────────────────────────────────────────────────────────

def check_volatility_regime(threshold_low: float = 0.80, threshold_high: float = 1.20) -> Dict:
    """
    基于PCR和成交额判断市场波动率状态

    Args:
        threshold_low: PCR偏低阈值（<0.8，低波动率环境）
        threshold_high: PCR偏高阈值（>1.1，高波动率/恐慌环境）

    Returns:
        dict: {regime, signal, description}
    """
    # 尝试最近交易日
    from datetime import timedelta
    df = None
    for days_back in range(1, 8):
        d = datetime.now() - timedelta(days=days_back)
        date_str = d.strftime('%Y%m%d')
        df = get_pcr_signals(date_str)
        if not df.empty:
            break

    if df is None or df.empty:
        return {'regime': 'unknown', 'signal': 'neutral', 'description': '无数据'}

    avg_pcr = df['vol_pcr'].mean()
    total_turnover = df['turnover'].sum()

    if avg_pcr < threshold_low:
        regime = 'low_vol'
        signal = 'calm'
        desc = f'低波动率环境(PCR={avg_pcr:.2f})，市场平稳，适合期权卖方'
    elif avg_pcr > threshold_high:
        regime = 'high_vol'
        signal = 'warning'
        desc = f'高波动率/恐慌环境(PCR={avg_pcr:.2f})，注意风险，期权买方机会'
    else:
        regime = 'normal'
        signal = 'neutral'
        desc = f'正常波动率环境(PCR={avg_pcr:.2f})'

    return {
        'regime': regime,
        'signal': signal,
        'avg_pcr': round(avg_pcr, 2),
        'total_turnover_wan': round(total_turnover, 0),
        'description': desc,
    }


if __name__ == '__main__':
    from datetime import timedelta
    # 找最近交易日
    date_str = None
    for days_back in range(1, 8):
        d = datetime.now() - timedelta(days=days_back)
        df = get_pcr_signals(d.strftime('%Y%m%d'))
        if not df.empty:
            date_str = d.strftime('%Y%m%d')
            break

    print("=== PCR情绪信号 ===")
    if date_str:
        df = get_pcr_signals(date_str)
        print(f"日期: {date_str}")
        print(df[['code','name','turnover','vol_pcr','oi_pcr','signal']].to_string(index=False))
        print()
    else:
        print("最近5个交易日均无数据")

    print("=== 沪深300ETF专项信号 ===")
    sig = get_pcr_signal_510300()
    print(sig)
    print()
    print("=== 波动率状态 ===")
    vol = check_volatility_regime()
    print(vol)
