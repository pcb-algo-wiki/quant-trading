#!/usr/bin/env python3
"""
美股每日扫描 + 微信推送
=========================
覆盖: 核心科技股 + AI产业链

用法:
  python scripts/us_stock_daily.py              # 扫描 + 推送
  python scripts/us_stock_daily.py --no-push    # 仅打印
  python scripts/us_stock_daily.py --force      # 强制刷新数据
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import argparse
from datetime import date, datetime

# 美股股票池
US_STOCKS = {
    # 核心层 - AI 算力
    "NVDA":  ("NVIDIA",     "AI算力", "GPU/AI芯片"),
    "AMD":   ("AMD",        "AI算力", "GPU/数据中心"),
    "AVGO":  ("博通",        "AI算力", "AI网络/存储"),

    # 卫星层 - AI 变现
    "MSFT":  ("微软",        "AI应用", "Copilot/企业AI"),
    "AMZN":  ("亚马逊",      "AI应用", "AWS AI/电商"),
    "META":  ("Meta",        "AI应用", "Llama/AI广告"),

    # 弹性层 - 高波动
    "SMCI":  ("超微电脑",    "AI服务器", "AI服务器/液冷"),
    "INTC":  ("英特尔",      "AI芯片", "困境反转/代工"),
    "GOOGL": ("谷歌",        "AI应用", "AI Search/云"),
    "TSLA":  ("特斯拉",      "新能源/AI", "FSD/机器人"),
}


def get_data(ticker: str, force: bool = False) -> dict:
    """获取个股数据 + 计算信号"""
    from data.yahoo_us import fetch_us_etf

    df = fetch_us_etf(ticker, start="2024-01-01", end=date.today().strftime("%Y-%m-%d"), force=force)
    if df.empty or len(df) < 60:
        return {"ticker": ticker, "error": "数据不足"}

    close = df["close"]

    # MA
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()

    current = close.iloc[-1]
    prev_close = close.iloc[-2] if len(close) > 1 else current

    # 趋势判断：MA20 与 MA60 关系 + 价格位置
    # 强势：MA20 > MA60，且价格在 MA20 之上
    # 动量向上：价格在 MA20 之上，但 MA20 ≤ MA60
    # 弱势：价格在 MA20 之下，MA20 < MA60
    # 震荡：其他情况
    if ma20.iloc[-1] > ma60.iloc[-1]:
        if current > ma20.iloc[-1]:
            trend = "强势"
        else:
            trend = "动量减弱"
    elif current > ma20.iloc[-1]:
        trend = "反弹"
    else:
        trend = "弱势"

    # 动量得分（20日强度）
    ret20 = (current / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0
    ret60 = (current / close.iloc[-60] - 1) * 100 if len(close) >= 60 else 0
    ret_ytd = (current / close.iloc[0] - 1) * 100 if len(close) >= 2 else 0

    # RSI(14) — RSI<35 超卖是买入机会，>75 超买是卖出/谨慎信号
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 0.001)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = rsi.iloc[-1] if not rsi.isna().all() else 50

    # 相对强弱（对比SPY）
    spy_df = fetch_us_etf("SPY", start="2024-01-01", end=date.today().strftime("%Y-%m-%d"))
    spy_ret = 0
    if not spy_df.empty and len(spy_df) >= 20:
        spy_ret = (spy_df["close"].iloc[-1] / spy_df["close"].iloc[-20] - 1) * 100
    rel_strength = ret20 - spy_ret

    # 综合评分（CANSLIM简化）
    score = 0
    if current > ma20.iloc[-1]: score += 20
    if ma20.iloc[-1] > ma60.iloc[-1]: score += 15
    if ma20.iloc[-1] > ma150.iloc[-1]: score += 15
    # RSI适中最好：40~70 是健康区间
    if 40 <= rsi_val <= 70: score += 10
    # 超卖 RSI<40 反而是加分（低位金叉机会）
    if rsi_val < 40: score += 8
    # 超买 RSI>75 扣分（过热风险）
    if rsi_val > 75: score -= 10
    if ret20 > 0: score += 15
    if rel_strength > 5: score += 15
    if current > prev_close: score += 10

    signal = "HOLD"
    # BUY: 得分够高 + 趋势向上（MA20>MA60）
    if score >= 65 and ma20.iloc[-1] > ma60.iloc[-1]:
        signal = "BUY"
    # SELL: 得分低 + 趋势向下（MA20<MA60） + 不是超卖状态
    elif score <= 40 and ma20.iloc[-1] < ma60.iloc[-1] and rsi_val >= 40:
        signal = "SELL"

    return {
        "ticker": ticker,
        "name": US_STOCKS.get(ticker, ("", ""))[0],
        "sector": US_STOCKS.get(ticker, ("", ""))[1],
        "current": round(current, 2),
        "prev_close": round(prev_close, 2),
        "change_pct": round((current / prev_close - 1) * 100, 2),
        "ma20": round(ma20.iloc[-1], 2) if not ma20.isna().all() else 0,
        "ma60": round(ma60.iloc[-1], 2) if not ma60.isna().all() else 0,
        "ma150": round(ma150.iloc[-1], 2) if not ma150.isna().all() else 0,
        "ma200": round(ma200.iloc[-1], 2) if not ma200.isna().all() else 0,
        "ret20": round(ret20, 1),
        "ret60": round(ret60, 1),
        "ret_ytd": round(ret_ytd, 1),
        "rsi": round(rsi_val, 1),
        "rel_strength": round(rel_strength, 1),
        "trend": trend,
        "score": score,
        "signal": signal,
    }


def build_report(results: list) -> dict:
    buys = sorted([r for r in results if r.get("signal") == "BUY"], key=lambda x: -x["score"])
    sells = sorted([r for r in results if r.get("signal") == "SELL"], key=lambda x: x["score"])
    holds = [r for r in results if r.get("signal") == "HOLD"]

    report = {
        "date": date.today().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "buys": buys,
        "sells": sells,
        "holds": holds,
        "total": len(results),
    }
    return report


def print_report(report: dict):
    print("=" * 70)
    print(f"  美股每日扫描  {report['date']} {report['time']}（美股收盘后数据）")
    print("=" * 70)

    # BUY
    if report["buys"]:
        print(f"\n🟢 买入信号 ({len(report['buys'])}只)")
        print(f"  {'代码':<8} {'名称':<10} {'现价':>8} {'20日':>8} {'RSI':>6} {'相对强弱':>8} {'趋势':<8} {'评分':>5}")
        print(f"  {'-'*70}")
        for r in report["buys"]:
            print(f"  {r['ticker']:<8} {r['name']:<10} ${r['current']:>7.2f} {r['ret20']:>+7.1f}% {r['rsi']:>5.1f} {r['rel_strength']:>+7.1f}% {r['trend']:<8} {r['score']:>5}")
            print(f"         MA20={r['ma20']:.2f} MA60={r['ma60']:.2f} MA200={r['ma200']:.2f}")

    # SELL
    if report["sells"]:
        print(f"\n🔴 卖出信号 ({len(report['sells'])}只)")
        print(f"  {'代码':<8} {'名称':<10} {'现价':>8} {'20日':>8} {'RSI':>6} {'趋势':<8} {'评分':>5}")
        print(f"  {'-'*70}")
        for r in report["sells"]:
            print(f"  {r['ticker']:<8} {r['name']:<10} ${r['current']:>7.2f} {r['ret20']:>+7.1f}% {r['rsi']:>5.1f} {r['trend']:<8} {r['score']:>5}")

    # HOLD
    if report["holds"]:
        print(f"\n⚪ 观望 ({len(report['holds'])}只)")
        for r in report["holds"]:
            print(f"  {r['ticker']:<8} {r['name']:<10} ${r['current']:>7.2f} {r['ret20']:>+7.1f}% RSI={r['rsi']:>5.1f}  {r['trend']}")

    print(f"\n{'='*70}")


def push_report(report: dict) -> bool:
    try:
        from utils.notify import notify

        title = f"📊 美股扫描 {report['date']}"

        data = {}

        if report["buys"]:
            buys_lines = [f"{r['ticker']} {r['name']}(${r['current']}) {r['ret20']:+.1f}% RSI={r['rsi']:.0f}" for r in report["buys"]]
            data["🟢 买入信号"] = " | ".join(buys_lines)

        if report["sells"]:
            sells_lines = [f"{r['ticker']} {r['name']}(${r['current']}) {r['ret20']:+.1f}% RSI={r['rsi']:.0f}" for r in report["sells"]]
            data["🔴 卖出信号"] = " | ".join(sells_lines)

        if report["holds"]:
            holds_lines = [f"{r['ticker']}(${r['current']}) {r['ret20']:+.1f}%" for r in report["holds"]]
            data["⚪ 观望"] = " | ".join(holds_lines)

        return notify(title, "INFO", data=data, pushplus_token=os.environ.get("PUSHPLUS_TOKEN", ""))
    except Exception as e:
        print(f"[ERROR] 推送失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="美股每日扫描")
    parser.add_argument("--no-push", action="store_true", help="仅打印不推送")
    parser.add_argument("--force", action="store_true", help="强制刷新数据")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  美股每日扫描  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print(f"\n⏳ 扫描 {len(US_STOCKS)} 只美股...")

    results = []
    for ticker in US_STOCKS:
        print(f"  正在获取 {ticker}...", end=" ")
        sys.stdout.flush()
        try:
            r = get_data(ticker, force=args.force)
            results.append(r)
            if r.get("error"):
                print(f"❌ {r['error']}")
            else:
                print(f"✅ ${r['current']:.2f} | {r['signal']} | RSI={r['rsi']:.0f} | 趋势={r['trend']}")
        except Exception as e:
            print(f"❌ {e}")
            results.append({"ticker": ticker, "name": US_STOCKS.get(ticker, ("",""))[0], "error": str(e)})

    report = build_report(results)
    print_report(report)

    if not args.no_push:
        push_token = os.environ.get("PUSHPLUS_TOKEN", "")
        if push_token:
            print("\n⏳ 推送到微信...")
            ok = push_report(report)
            print(f"  {'✅ 推送成功' if ok else '❌ 推送失败'}")
        else:
            print("\n💡 提示: 设置 PUSHPLUS_TOKEN 环境变量即可推送微信")


if __name__ == "__main__":
    main()
