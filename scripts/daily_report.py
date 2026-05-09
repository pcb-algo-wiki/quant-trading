#!/usr/bin/env python3
"""
scripts/daily_report.py
=======================
每日量化报告自动推送

功能:
- 获取最新行情数据
- 运行最优策略回测
- 获取资金流向/新闻情绪
- 推送日报到微信

用法:
  python scripts/daily_report.py                    # 直接运行
  python scripts/daily_report.py --push             # 推送到微信
  python scripts/daily_report.py --no-push         # 仅打印，不推送

Cron定时任务（每天早上9点）:
  0 9 * * * /Users/tanwei/quant-trading/.venv/bin/python \
    /Users/tanwei/quant-trading/scripts/daily_report.py --push >> \
    ~/.hermes/cron/daily_report.log 2>&1
"""

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime, date
from typing import Optional

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 环境变量
os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))


def get_latest_prices(etfs: list) -> dict:
    """获取最新价格"""
    prices = {}
    try:
        import akshare as ak
        for code in etfs:
            try:
                df = ak.stock_zh_a_spot_em()
                row = df[df["代码"] == code]
                if not row.empty:
                    prices[code] = float(row["最新价"].values[0])
            except:
                pass
    except:
        pass
    return prices


def run_strategy_check(symbol: str, strategy_name: str = "MA(15,20)") -> dict:
    """
    运行策略检查
    Returns: {signal, score, last_return, trend}
    """
    try:
        from data.fetcher import fetch_etf
        from strategies.ma_optimized import MAOptimizedStrategy
        from backtest.engine import BacktestEngine

        # 使用Yahoo数据（最新）
        os.environ["USE_YAHOO"] = "1"
        df = fetch_etf(symbol, "20230101", date.today().strftime("%Y%m%d"))
        if df.empty or len(df) < 30:
            return {"signal": "unknown", "error": "数据不足"}

        # 简单MA信号
        ma_fast = df["close"].rolling(15).mean()
        ma_slow = df["close"].rolling(20).mean()
        current = df["close"].iloc[-1]

        if ma_fast.iloc[-1] > ma_slow.iloc[-1]:
            signal = "buy"
        elif ma_fast.iloc[-1] < ma_slow.iloc[-1]:
            signal = "sell"
        else:
            signal = "hold"

        # 近5日收益
        recent_return = (df["close"].iloc[-1] / df["close"].iloc[-5] - 1) * 100 if len(df) >= 5 else 0
        ytd_return = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100

        return {
            "signal": signal,
            "last_price": round(current, 3),
            "ma_fast": round(ma_fast.iloc[-1], 3) if not ma_fast.isna().all() else 0,
            "ma_slow": round(ma_slow.iloc[-1], 3) if not ma_slow.isna().all() else 0,
            "recent_5d_return": round(recent_return, 2),
            "ytd_return": round(ytd_return, 2),
        }
    except Exception as e:
        return {"signal": "error", "error": str(e)}


def get_market_sentiment() -> dict:
    """获取市场情绪"""
    try:
        from data.realtime_news import get_realtime_news, get_market_summary

        news_df = get_realtime_news()
        if news_df.empty:
            return {"sentiment": 0.5, "news_count": 0}

        summary = get_market_summary(news_df)
        return {
            "sentiment": summary.get("平均情感", 0.5),
            "news_count": summary.get("总条数", 0),
            "market_mood": summary.get("市场情绪", "中性"),
            "positive_count": summary.get("偏多", 0),
            "negative_count": summary.get("偏空", 0),
        }
    except Exception as e:
        return {"sentiment": 0.5, "news_count": 0, "error": str(e)}


def get_fund_flow_signal(etf: str = "159915") -> dict:
    """获取资金流向信号"""
    try:
        from data.macro_event import get_fund_flow, analyze_fund_flow

        flow_df = get_fund_flow(etf)
        if flow_df.empty:
            return {"signal": "neutral", "score": 0.5}

        result = analyze_fund_flow(flow_df, lookback=5)
        return result
    except Exception as e:
        return {"signal": "neutral", "error": str(e)}


def get_pcr_signals_data() -> dict:
    """获取期权PCR情绪信号"""
    try:
        from data.option_signals import get_pcr_signals, get_pcr_signal_510300, check_volatility_regime

        sig = get_pcr_signal_510300()
        vol = check_volatility_regime()

        return {
            "510300_pcr": sig.get("pcr", None),
            "510300_oi_pcr": sig.get("oi_pcr", None),
            "510300_signal": sig.get("signal", "unknown"),
            "510300_score": sig.get("signal_score", 0),
            "510300_interp": sig.get("interpretation", ""),
            "vol_regime": vol.get("regime", "unknown"),
            "vol_avg_pcr": float(vol.get("avg_pcr", 0)) if vol.get("avg_pcr") is not None else None,
            "vol_desc": vol.get("description", ""),
        }
    except Exception as e:
        return {"error": str(e)}


def get_stock_picks() -> dict:
    """
    获取个股精选（从缓存读取，秒级）
    返回各板块Top3 Buy信号个股
    """
    try:
        from data.stock_screener import get_top_picks

        sectors = {
            "AI算力": "AI算力",
            "AI应用": "AI应用",
            "光通信": "光通信",
            "通信设备": "通信设备",
            "半导体": "半导体",
            "新能源车": "新能源车",
            "军工": "军工",
            "消费": "消费",
            "金融": "金融",
        }

        picks = {}
        for label, sector in sectors.items():
            df = get_top_picks(n=3, sector=sector)
            if df is not None and not df.empty:
                buys = df[df['signal'] == 'Buy'].head(3)
                if not buys.empty:
                    picks[label] = [
                        {
                            "name": row['name'],
                            "score": round(row['score'], 1),
                            "ret20d": f"{row['ret_20d']:.1f}%" if row.get('ret_20d') else "N/A",
                        }
                        for _, row in buys.iterrows()
                    ]

        total_buys = sum(len(v) for v in picks.values())
        return {"picks": picks, "total_buys": total_buys, "error": None}
    except Exception as e:
        return {"picks": {}, "total_buys": 0, "error": str(e)}


def build_report(
    strategy_results: dict,
    sentiment: dict,
    fund_flow: dict,
    pcr_data: dict = None,
    stock_picks: dict = None,
) -> dict:
    """构建报告数据"""

    # 汇总信号
    signals = []
    for symbol, result in strategy_results.items():
        sig = result.get("signal", "unknown")
        if sig == "buy":
            signals.append(("buy", symbol, result))
        elif sig == "sell":
            signals.append(("sell", symbol, result))
        else:
            signals.append(("hold", symbol, result))

    # 综合信号
    buy_signals = [s for s in signals if s[0] == "buy"]
    sell_signals = [s for s in signals if s[0] == "sell"]

    if len(buy_signals) > len(sell_signals):
        composite = "🟢 买入信号"
    elif len(sell_signals) > len(buy_signals):
        composite = "🔴 卖出信号"
    else:
        composite = "⚪ 观望"

    # 情感
    sent = sentiment.get("sentiment", 0.5)
    sent_label = "🟢偏多" if sent > 0.55 else "🔴偏空" if sent < 0.45 else "⚪中性"

    # 资金流
    flow_sig = fund_flow.get("signal", "neutral")
    flow_label = {"bullish": "🟢主力净流入", "bearish": "🔴主力净流出", "neutral": "⚪中性"}.get(flow_sig, "⚪中性")

    # PCR情绪
    pcr_label = ""
    pcr_score = 0
    if pcr_data and not pcr_data.get("error"):
        score = pcr_data.get("510300_score", 0)
        pcr_score = score
        if score >= 2:
            pcr_label = "🟢极度看多"
        elif score == 1:
            pcr_label = "🟢偏多"
        elif score == 0:
            pcr_label = "⚪中性"
        elif score == -1:
            pcr_label = "🔴偏空"
        else:
            pcr_label = "🔴极度看空"

    report = {
        "title": f"量化日报 {date.today().strftime('%Y-%m-%d')}",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "composite_signal": composite,
        "market_sentiment": sent_label,
        "fund_flow": flow_label,
        "pcr_label": pcr_label,
        "pcr_data": pcr_data or {},
        "news_count": sentiment.get("news_count", 0),
        "stock_picks": stock_picks or {},
        "strategies": [],
    }

    for symbol, result in strategy_results.items():
        report["strategies"].append({
            "symbol": symbol,
            "name": _symbol_name(symbol),
            "signal": result.get("signal", "?").upper(),
            "price": result.get("last_price", 0),
            "ma_fast": result.get("ma_fast", 0),
            "ma_slow": result.get("ma_slow", 0),
            "recent_5d": f"{result.get('recent_5d_return', 0):+.2f}%",
            "ytd": f"{result.get('ytd_return', 0):+.2f}%",
        })

    return report


def _symbol_name(code: str) -> str:
    names = {
        "510300": "沪深300ETF",
        "510500": "中证500ETF",
        "159915": "创业板ETF",
        "512100": "纳指ETF",
    }
    return names.get(code, code)


def print_report(report: dict):
    """打印报告到终端"""
    print("=" * 60)
    print(f"  {report['title']}")
    print(f"  生成时间: {report['time']}")
    print("=" * 60)
    print(f"  综合信号: {report['composite_signal']}")
    print(f"  市场情绪: {report['market_sentiment']} ({report['news_count']}条新闻)")
    print(f"  资金流向: {report['fund_flow']}")
    pcr_label = report.get('pcr_label', '')
    if pcr_label:
        print(f"  期权PCR: {pcr_label}")
        pcr_data = report.get('pcr_data', {})
        if pcr_data.get('510300_pcr'):
            interp = pcr_data.get('510300_interp', '')
            print(f"           沪深300 vol_PCR={pcr_data['510300_pcr']:.3f}  oi_PCR={pcr_data.get('510300_oi_pcr', 0):.3f}  {interp}")
        vol_desc = pcr_data.get('vol_desc', '')
        if vol_desc:
            print(f"           {vol_desc}")
    print()
    print(f"  {'标的':<10} {'信号':>5} {'最新价':>8} {'MA15':>8} {'MA20':>8} {'5日':>8} {'今年来':>8}")
    print(f"  {'-'*60}")
    for s in report["strategies"]:
        print(f"  {s['name']:<10} {s['signal']:>5} {s['price']:>8.3f} "
              f"{s['ma_fast']:>8.3f} {s['ma_slow']:>8.3f} "
              f"{s['recent_5d']:>8} {s['ytd']:>8}")

    # 个股精选
    stock_picks = report.get('stock_picks', {})
    if stock_picks.get('picks') and not stock_picks.get('error'):
        print()
        print(f"  {'─'*60}")
        print(f"  📈 个股精选（共{stock_picks.get('total_buys', 0)}只Buy信号）")
        for sector, stocks in stock_picks['picks'].items():
            names = ' / '.join([f"{s['name']}({s['score']}分)" for s in stocks])
            print(f"  {sector:<8}: {names}")
    print("=" * 60)


def push_report(report: dict) -> bool:
    """推送报告到微信"""
    try:
        from utils.notify import notify
        import requests

        # PCR信息
        pcr_data = report.get('pcr_data', {})
        pcr_line = ""
        if pcr_data.get('510300_pcr'):
            pcr_line = (f"<p>期权PCR | vol_PCR={pcr_data['510300_pcr']:.3f} | "
                        f"oi_PCR={pcr_data.get('510300_oi_pcr', 0):.3f} | "
                        f"{pcr_data.get('510300_interp', '')}</p>")

        # 构建HTML内容
        lines = [
            f"<h2>📊 {report['title']}</h2>",
            f"<p style='color:#888'>{report['time']}</p>",
            f"<h3>信号: {report['composite_signal']}</h3>",
            f"<p>情绪: {report['market_sentiment']} | "
            f"新闻: {report['news_count']}条 | "
            f"资金: {report['fund_flow']}</p>",
            pcr_line,
            "<table border='1' cellpadding='6' style='border-collapse:collapse;width:100%'>",
            "<tr style='background:#f5f5f5'>"
            "<th>标的</th><th>信号</th><th>最新价</th>"
            "<th>MA15</th><th>MA20</th><th>5日</th><th>今年来</th></tr>",
        ]

        for s in report["strategies"]:
            color = "#4ade80" if s["signal"] == "BUY" else "#f87171" if s["signal"] == "SELL" else "#888"
            lines.append(
                f"<tr><td>{s['name']}</td>"
                f"<td style='color:{color};font-weight:bold'>{s['signal']}</td>"
                f"<td>{s['price']:.3f}</td>"
                f"<td>{s['ma_fast']:.3f}</td>"
                f"<td>{s['ma_slow']:.3f}</td>"
                f"<td>{s['recent_5d']}</td>"
                f"<td>{s['ytd']}</td></tr>"
            )
        lines.append("</table>")

        # 个股精选
        stock_picks = report.get('stock_picks', {})
        if stock_picks.get('picks') and not stock_picks.get('error'):
            picks = stock_picks['picks']
            total = stock_picks.get('total_buys', 0)
            lines.append(f"<h4>📈 个股精选（共{total}只Buy）</h4>")
            lines.append("<table border='1' cellpadding='6' style='border-collapse:collapse;width:100%'>")
            lines.append("<tr style='background:#f0f0f0'><th>板块</th><th>推荐个股</th></tr>")
            for sector, stocks in picks.items():
                names = ' / '.join([f"{s['name']}({s['score']}分,{s['ret20d']})" for s in stocks])
                lines.append(f"<tr><td>{sector}</td><td>{names}</td></tr>")
            lines.append("</table>")

        content = "\n".join(lines)
        title = f"📊 {report['title']} | {report['composite_signal']}"

        return notify(title, "INFO", pushplus_token=os.environ.get("PUSHPLUS_TOKEN", ""))
    except Exception as e:
        print(f"[ERROR] 推送失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="每日量化报告")
    parser.add_argument("--push", action="store_true", help="推送到微信")
    parser.add_argument("--no-push", action="store_true", help="仅打印不推送")
    parser.add_argument("--symbols", default="510300,510500,159915", help="标的列表")
    args = parser.parse_args()

    symbols = args.symbols.split(",")

    print("=" * 60)
    print("  每日量化报告")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 策略检查
    print("\n⏳ 运行策略检查...")
    strategy_results = {}
    for sym in symbols:
        result = run_strategy_check(sym)
        strategy_results[sym] = result
        sig = result.get("signal", "?")
        print(f"  {sym}: {sig.upper()} @ {result.get('last_price', 'N/A')}")

    # 2. 市场情绪
    print("\n⏳ 获取市场情绪...")
    sentiment = get_market_sentiment()
    print(f"  情感: {sentiment.get('sentiment', 0.5):.3f} | "
          f"新闻: {sentiment.get('news_count', 0)}条 | "
          f"市场: {sentiment.get('market_mood', '?')}")

    # 3. 资金流向
    print("\n⏳ 获取资金流向...")
    fund_flow = get_fund_flow_signal("159915")
    print(f"  信号: {fund_flow.get('signal', '?')} | "
          f"评分: {fund_flow.get('score', 0):.3f}")

    # 4. PCR情绪
    print("\n⏳ 获取期权PCR情绪...")
    pcr_data = get_pcr_signals_data()
    if pcr_data.get("error"):
        print(f"  PCR: 获取失败 ({pcr_data.get('error')})")
    else:
        print(f"  沪深300: vol_PCR={pcr_data.get('510300_pcr', 'N/A')}  "
              f"oi_PCR={pcr_data.get('510300_oi_pcr', 'N/A')}  "
              f"信号={pcr_data.get('510300_signal', '?')}  "
              f"{pcr_data.get('510300_interp', '')}")
        print(f"  波动率: {pcr_data.get('vol_desc', 'N/A')}")

    # 5. 个股精选（读缓存）
    print("\n⏳ 获取个股精选（读缓存）...")
    stock_picks = get_stock_picks()
    if stock_picks.get('error'):
        print(f"  个股: 获取失败 ({stock_picks.get('error')})")
    elif stock_picks.get('picks'):
        total = stock_picks.get('total_buys', 0)
        print(f"  Buy信号共{total}只:")
        for sector, stocks in list(stock_picks['picks'].items())[:5]:
            names = ', '.join([s['name'] for s in stocks])
            print(f"    {sector}: {names}")
    else:
        print(f"  个股: 缓存为空（需先运行全量扫描 scripts/stock_daily.py）")

    # 6. 构建报告
    print("\n⏳ 构建报告...")
    report = build_report(strategy_results, sentiment, fund_flow, pcr_data, stock_picks)
    print_report(report)

    # 7. 推送
    if args.push or not args.no_push:
        push_token = os.environ.get("PUSHPLUS_TOKEN", "")
        if push_token:
            print("\n⏳ 推送到微信...")
            ok = push_report(report)
            print(f"  {'✅ 推送成功' if ok else '❌ 推送失败'}")
        else:
            print("\n💡 提示: 设置 PUSHPLUS_TOKEN 环境变量即可推送微信")

    print()


if __name__ == "__main__":
    main()
