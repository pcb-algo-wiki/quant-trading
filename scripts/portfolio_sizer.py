#!/usr/bin/env python3
"""
组合仓位计算器 — 凯利公式 + 风险预算
Usage: python scripts/portfolio_sizer.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

# ── 配置区 ──────────────────────────────────────────────────────────────────
TOTAL_CAPITAL = 500_000  # 总本金（元）
MAX_POSITIONS = 5        # 最大持仓标的数

# A股各标的配置
ETFS = {
    "510300": {"name": "沪深300ETF", "weight": 0.20},
    "510500": {"name": "中证500ETF", "weight": 0.15},
    "159915": {"name": "创业板ETF",  "weight": 0.15},
}

US_STOCKS = {
    "NVDA":  {"name": "英伟达",    "weight": 0.10},
    "AMD":   {"name": "AMD",        "weight": 0.08},
    "AVGO":  {"name": "博通",       "weight": 0.08},
}

# A股个股（从 stock_daily.py 缓存读取 top picks）
INDIVIDUAL_STOCKS_CONFIG = {
    "SEMI":     {"name": "半导体",   "weight": 0.10},
    "AI":       {"name": "AI算力",   "weight": 0.07},
    "AEROSPACE": {"name": "航天",   "weight": 0.05},
    "DEFENSE":  {"name": "军工",    "weight": 0.02},
}


def calc_kelly(win_rate: float, avg_win: float, avg_loss: float, fraction: float = 0.5) -> dict:
    """
    计算凯利公式（带波动率调整）
    f* = (bp - q) / b
    b = avg_win / avg_loss（盈亏比）
    p = win_rate（胜率）
    q = 1 - p

    fraction: 实际使用比例（默认半凯利 = 0.5），防止过拟合
    """
    if win_rate <= 0 or avg_loss <= 0:
        return {"f": 0, "b": 0, "p": win_rate, "label": "无数据"}

    b = avg_win / avg_loss  # 赔率
    p = win_rate
    q = 1 - p

    f_star = (b * p - q) / b  # 原始凯利
    f_adj  = max(0, min(f_star * fraction, 0.4))  # 半凯利，上限40%

    if f_adj <= 0:
        label = "❌ 不建议开仓"
    elif f_adj < 0.05:
        label = "⚠️ 轻仓试探"
    elif f_adj < 0.15:
        label = "⚙️ 正常仓位"
    else:
        label = "💰 可加重仓"

    return {
        "f": round(f_adj * 100, 1),  # 仓位百分比
        "b": round(b, 2),            # 盈亏比
        "p": round(p * 100, 1),      # 胜率
        "f_star": round(f_star * 100, 1),
        "label": label,
    }


def calc_volatility(df: pd.DataFrame, window: int = 20) -> float:
    """计算年化波动率"""
    if len(df) < window + 1:
        return 0.30  # 默认30%
    returns = df["close"].pct_change().dropna()
    vol = returns.rolling(window).std().iloc[-1] * np.sqrt(252)
    return float(vol) if not np.isnan(vol) else 0.30


def calc_sharpe(df: pd.DataFrame, window: int = 60) -> float:
    """计算夏普比率（简化）"""
    if len(df) < window:
        return 0
    returns = df["close"].pct_change().dropna().tail(window)
    if len(returns) < 2:
        return 0
    sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
    return round(float(sharpe), 2)


def get_risk_budget(etf_signals: dict, etf_vols: dict, total: float = TOTAL_CAPITAL) -> list:
    """
    基于信号强度 + 波动率 + 凯利计算仓位
    返回: [(标的名, 建议仓位占比, 金额, 说明), ...]
    """
    results = []

    # 1. ETF仓位（固定权重 × 信号强度调整）
    for symbol, cfg in ETFS.items():
        sig = etf_signals.get(symbol, {})
        vol = etf_vols.get(symbol, 0.20)
        signal = sig.get("signal", "hold")
        strength = sig.get("signal_strength", 0) / 4  # 归一化 0~1

        base_w = cfg["weight"]

        if signal == "buy":
            if strength >= 0.75:  # 4票全同
                adj_w = base_w * 1.2
                reason = f"🟢强Buy({sig.get('votes','')})，凯利仓位上调"
            elif strength >= 0.5:  # 3票
                adj_w = base_w
                reason = f"🟢 Buy({sig.get('votes','')})"
            else:
                adj_w = base_w * 0.8
                reason = f"🟢 Buy(偏弱)，轻仓"
        elif signal == "sell":
            adj_w = base_w * 0.3
            reason = f"🔴 SELL({sig.get('votes','')}), 减仓"
        else:
            adj_w = base_w * 0.5
            reason = "⚪ HOLD，降低仓位"

        amount = int(total * min(adj_w, 0.40))  # 单标上限40%
        results.append({
            "name": cfg["name"],
            "symbol": symbol,
            "weight": round(adj_w * 100, 1),
            "amount": amount,
            "vol": round(vol * 100, 1),
            "signal": signal,
            "reason": reason,
        })

    # 2. 美股仓位
    for symbol, cfg in US_STOCKS.items():
        sig = etf_signals.get(symbol, {})
        vol = etf_vols.get(symbol, 0.35)
        signal = sig.get("signal", "hold")
        strength = sig.get("signal_strength", 0) / 4 if sig else 0

        if signal == "buy" and strength >= 0.5:
            adj_w = cfg["weight"]
            reason = f"🟢 Buy({sig.get('votes','')})"
        elif signal == "buy":
            adj_w = cfg["weight"] * 0.7
            reason = f"🟢 Buy(弱)"
        elif signal == "sell":
            adj_w = cfg["weight"] * 0.2
            reason = f"🔴 SELL, 止损"
        else:
            adj_w = cfg["weight"] * 0.5
            reason = "⚪ HOLD"

        amount = int(total * min(adj_w, 0.25))  # 美股单标上限25%
        results.append({
            "name": cfg["name"],
            "symbol": symbol,
            "weight": round(adj_w * 100, 1),
            "amount": amount,
            "vol": round(vol * 100, 1),
            "signal": signal,
            "reason": reason,
        })

    return results


def fetch_and_analyze() -> dict:
    """获取数据并计算仓位"""
    import os
    os.environ["USE_YAHOO"] = "1"

    from data.fetcher import fetch_etf
    from data.yahoo_us import fetch_us_etf as fetch_us_stock

    end = date.today().strftime("%Y%m%d")

    etf_signals = {}
    etf_vols = {}
    etf_sharpes = {}

    # A股ETF
    for symbol in ETFS.keys():
        try:
            df = fetch_etf(symbol, "20230101", end)
            if df.empty or len(df) < 60:
                continue

            vol = calc_volatility(df)
            etf_vols[symbol] = vol
            etf_sharpes[symbol] = calc_sharpe(df)

            close = df["close"]
            ma_fast = close.rolling(15).mean().iloc[-1]
            ma_slow = close.rolling(20).mean().iloc[-1]
            current = close.iloc[-1]

            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, 0.001)
            rsi = (100 - (100 / (1 + rs))).iloc[-1]

            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd = (ema12 - ema26).iloc[-1]

            ma_sig = "buy" if ma_fast > ma_slow else "sell" if ma_fast < ma_slow else "hold"
            rsi_sig = "buy" if rsi < 40 else "sell" if rsi > 70 else "hold"
            macd_sig = "buy" if macd > 0 else "sell" if macd < 0 else "hold"

            votes = [ma_sig, rsi_sig, macd_sig]
            buy_v = votes.count("buy")
            sell_v = votes.count("sell")
            signal = "buy" if buy_v > sell_v else "sell" if sell_v > buy_v else "hold"

            etf_signals[symbol] = {
                "signal": signal,
                "signal_strength": max(buy_v, sell_v),
                "rsi": round(float(rsi), 1),
                "votes": f"{buy_v}Buy/{sell_v}Sell",
                "price": round(float(current), 3),
            }
        except Exception as e:
            print(f"[{symbol}] 分析失败: {e}")

    # 美股（用yfinance原生）
    for symbol in US_STOCKS.keys():
        try:
            df = fetch_us_stock(symbol, "20230101", end)
            if df.empty or len(df) < 60:
                print(f"[{symbol}] 数据不足")
                continue

            vol = calc_volatility(df)
            etf_vols[symbol] = vol
            etf_sharpes[symbol] = calc_sharpe(df)

            close = df["close"]
            ma_fast = close.rolling(15).mean().iloc[-1]
            ma_slow = close.rolling(20).mean().iloc[-1]
            current = close.iloc[-1]

            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, 0.001)
            rsi = (100 - (100 / (1 + rs))).iloc[-1]

            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd = (ema12 - ema26).iloc[-1]

            ma_sig = "buy" if ma_fast > ma_slow else "sell" if ma_fast < ma_slow else "hold"
            rsi_sig = "buy" if rsi < 40 else "sell" if rsi > 70 else "hold"
            macd_sig = "buy" if macd > 0 else "sell" if macd < 0 else "hold"

            votes = [ma_sig, rsi_sig, macd_sig]
            buy_v = votes.count("buy")
            sell_v = votes.count("sell")
            signal = "buy" if buy_v > sell_v else "sell" if sell_v > buy_v else "hold"

            etf_signals[symbol] = {
                "signal": signal,
                "signal_strength": max(buy_v, sell_v),
                "rsi": round(float(rsi), 1),
                "votes": f"{buy_v}Buy/{sell_v}Sell",
                "price": round(float(current), 3),
            }
        except Exception as e:
            print(f"[{symbol}] 分析失败: {e}")

    # 仓位计算
    positions = get_risk_budget(etf_signals, etf_vols)

    # 总计
    total_weight = sum(p["weight"] for p in positions)
    total_amount = sum(p["amount"] for p in positions)

    return {
        "positions": positions,
        "total_weight": round(total_weight, 1),
        "total_amount": total_amount,
        "remaining": TOTAL_CAPITAL - total_amount,
        "signals": etf_signals,
        "sharpes": etf_sharpes,
    }


def print_sizer_report(result: dict):
    """打印仓位报告"""
    print("=" * 65)
    print(f"  组合仓位建议  ({TOTAL_CAPITAL/10000:.0f}万本金)")
    print("=" * 65)
    print(f"  {'标的':<12} {'信号':>5} {'建议权重':>8} {'金额(元)':>10} {'波动率':>7} {'依据'}")
    print(f"  {'-'*65}")

    for p in result["positions"]:
        print(f"  {p['name']:<12} {p['signal']:>5} {p['weight']:>7.1f}% {p['amount']:>10,} {p['vol']:>6.1f}%  {p['reason']}")

    print(f"  {'-'*65}")
    print(f"  {'合计':<12} {'':>5} {result['total_weight']:>7.1f}% {result['total_amount']:>10,}  剩余{int(result['remaining']):,}元")
    print()
    print(f"  💰 总仓位 {result['total_weight']:.0f}% | 剩余子弹 {int(result['remaining']):,}元")

    sharpes = result.get("sharpes", {})
    if sharpes:
        print()
        print(f"  {'标的':<12} {'夏普比率':>8}")
        print(f"  {'-'*22}")
        for sym, cfg in {**ETFS, **US_STOCKS}.items():
            sh = sharpes.get(sym, None)
            if sh is not None:
                bar = "⭐" * min(int(sh), 5)
                print(f"  {cfg['name']:<12} {sh:>8.2f}  {bar}")


if __name__ == "__main__":
    print("⏳ 分析组合仓位...")
    result = fetch_and_analyze()
    print_sizer_report(result)
