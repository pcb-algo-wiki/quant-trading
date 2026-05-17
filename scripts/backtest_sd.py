#!/usr/bin/env python3
"""
score_supply_demand.py 三维评分系统回测 v2
============================================
更完整的回测:
  - 每日评分，每5日调仓
  - 回测区间: 2025-11-03 ~ 2026-05-08
  - 对比基准: 半导体ETF (512100)
"""

import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────────────────────
# 数据加载
# ─────────────────────────────────────────────────────────────────────────────

def load_stock_price(ticker: str) -> pd.DataFrame:
    p = Path(f"data/cache/stocks/{ticker}.pkl")
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_pickle(p)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "close"]]

def load_etf(sym: str) -> pd.DataFrame:
    p = Path(f"data/cache/etf_{sym}.pkl")
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_pickle(p)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "close"]]

# ─────────────────────────────────────────────────────────────────────────────
# 评分计算
# ─────────────────────────────────────────────────────────────────────────────

def get_news_score(segment: str, ref_date: str, conn) -> float:
    """新闻催化评分 (0-10)，ref_date之前90天内"""
    try:
        keywords = {
            "光模块": ["光模块", "800G", "1.6T", "光通信"],
            "光芯片": ["光芯片", "VCSEL", "DFB", "激光器"],
            "存储制造": ["存储", "NAND", "DRAM", "HBM"],
            "减速器": ["减速器", "谐波", "RV减速"],
            "正极材料": ["正极", "三元", "磷酸铁锂"],
            "负极材料": ["负极", "石墨"],
            "隔膜": ["隔膜", "湿法隔膜"],
            "电解液": ["电解液"],
            "电芯/PACK": ["电芯", "动力电池", "储能电池"],
            "伺服驱动": ["伺服", "伺服驱动"],
            "控制器": ["控制器", "PLC", "数控"],
            "传感器": ["传感器", "MEMS", "力传感器"],
            "机器人本体": ["人形机器人", "工业机器人"],
            "高温合金/钛合金": ["高温合金", "钛合金"],
            "航发整机": ["航发", "航空发动机"],
            "军机/无人机": ["军机", "无人机", "军用飞机"],
            "导弹/精确制导": ["导弹", "制导"],
            "军工信息化": ["军工", "连接器", "信息化"],
            "商业航天": ["商业航天", "卫星", "火箭"],
            "HBM/高带宽存储": ["HBM", "高带宽存储"],
            "封装测试": ["封装", "封测", "先进封装"],
            "硅片/晶圆": ["硅片", "晶圆"],
            "晶圆代工": ["晶圆代工", "Foundry"],
            "半导体设备": ["半导体设备", "半导体装备"],
            "存储封测": ["存储封测"],
            "模组/SSD": ["模组", "SSD", "存储模组"],
            "锂电设备": ["锂电设备"],
            "PCB/载板": ["PCB", "载板"],
        }
        seg_keywords = keywords.get(segment, [segment])
        like_clause = " OR ".join([f"title LIKE '%{k}%'" for k in seg_keywords])
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*) FROM news_items
            WHERE ({like_clause})
            AND datetime(published_at) >= datetime('{ref_date}', '-90 days')
            AND datetime(published_at) <= datetime('{ref_date}')
        """)
        count = cur.fetchone()[0]
        if count >= 20: return 8.0
        elif count >= 10: return 6.5
        elif count >= 5: return 5.0
        elif count >= 2: return 4.0
        elif count >= 1: return 3.0
        else: return 2.0
    except:
        return 5.0

def compute_cycle_score(segment: str) -> float:
    """供需周期评分 (0-10)"""
    from knowledge.supply_chain import get_supply_demand_gap, CYCLE_PHASES
    phases = [p for p in CYCLE_PHASES if p.segment == segment]
    if not phases:
        return 5.0
    phases_sorted = sorted(phases, key=lambda p: (int(p.start_period.split("Q")[0]), int(p.start_period.split("Q")[1])))
    current = None
    for i in range(len(phases_sorted) - 1, -1, -1):
        if phases_sorted[i].end_period is None:
            current = phases_sorted[i]
            break
    if current is None:
        return 5.0
    phase_score_map = {"紧缺": 9.0, "均衡": 5.0, "去化": 4.0, "过剩": 2.0}
    base = phase_score_map.get(current.phase, 5.0)
    gap = get_supply_demand_gap(segment, 0)
    gap_abs = abs(gap["gap_pct"])
    if gap["gap_pct"] > 0:
        gap_bonus = min(gap_abs / 10, 1.5)
    else:
        gap_bonus = -min(gap_abs / 10, 1.0)
    return max(0, min(10, base + gap_bonus))

def compute_position_score(df: pd.DataFrame, date_idx: int) -> tuple:
    """(score, price_position, ret_1y)"""
    if df is None or len(df) < 60 or date_idx < 60:
        return 5.0, 1.0, 0.0
    now_price = df["close"].iloc[date_idx]
    start_idx = max(0, date_idx - 252)
    high_252 = df["high"].iloc[start_idx:date_idx+1].max() if "high" in df.columns else df["close"].iloc[start_idx:date_idx+1].max()
    low_252 = df["low"].iloc[start_idx:date_idx+1].min() if "low" in df.columns else df["close"].iloc[start_idx:date_idx+1].min()
    if high_252 <= 0:
        return 5.0, 1.0, 0.0
    price_position = now_price / high_252
    start_252 = max(0, date_idx - 252)
    price_252_ago = df["close"].iloc[start_252]
    ret_1y = (now_price / price_252_ago - 1) * 100 if price_252_ago > 0 else 0.0
    if price_position >= 0.9:
        ps = 2.0
    elif price_position >= 0.75:
        ps = 4.0
    elif price_position >= 0.55:
        ps = 6.5
    elif price_position >= 0.35:
        ps = 8.5
    else:
        ps = 7.0
    if ret_1y > 150 and price_position > 0.85:
        ps = 3.0
    elif ret_1y > 80 and price_position > 0.80:
        ps = 4.0
    return ps, price_position, ret_1y

def compute_total_score(cycle_sc: float, pos_sc: float, news_sc: float) -> float:
    """综合评分 = 供需×0.4 + 位置×0.3 + 新闻×0.3"""
    return round(cycle_sc * 0.4 + pos_sc * 0.3 + news_sc * 0.3, 2)

# ─────────────────────────────────────────────────────────────────────────────
# 主回测
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest():
    from knowledge.supply_chain import get_stock_by_segment, get_all_chain_segments
    from data.stock_pool import ALL_STOCKS

    print("=" * 72)
    print("  score_supply_demand.py 三维评分系统回测")
    print("  回测区间: 2025-11-03 ~ 2026-05-08")
    print("=" * 72)

    # ── 1. 加载数据 ─────────────────────────────────────────────────────────
    cached = set(p.stem for p in Path("data/cache/stocks").glob("*.pkl"))
    pool_codes = set(ALL_STOCKS.keys())
    targets = {t: ALL_STOCKS[t] for t in (pool_codes & cached)}
    print(f"\n股票池: {len(targets)} 只有缓存数据")

    prices = {}
    for ticker in targets:
        df = load_stock_price(ticker)
        if len(df) > 100:
            prices[ticker] = df

    # 加载完整行情（含open/high/low）用于位置计算
    prices_full = {}
    for ticker in targets:
        p = Path(f"data/cache/stocks/{ticker}.pkl")
        if p.exists():
            df = pd.read_pickle(p)
            if "date" in df.columns and len(df) > 100:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                prices_full[ticker] = df

    benchmark_df = load_etf("512100")
    start_dt = pd.Timestamp("2025-11-01")
    end_dt = pd.Timestamp("2026-05-08")
    benchmark_df = benchmark_df[
        (benchmark_df["date"] >= start_dt) & (benchmark_df["date"] <= end_dt)
    ].reset_index(drop=True)
    print(f"基准: 512100 半导体ETF, {len(benchmark_df)} 个交易日")
    print(f"      {benchmark_df['date'].min().date()} ~ {benchmark_df['date'].max().date()}")

    # ── 2. 新闻数据库 ────────────────────────────────────────────────────────
    conn = sqlite3.connect("data/cache/quant_data.db")

    # ── 3. 建立股票→环节映射 ────────────────────────────────────────────────
    stock_seg = {}  # ticker -> (segment, name)
    for seg in get_all_chain_segments():
        for ticker, name in get_stock_by_segment(seg):
            if ticker in prices_full:
                stock_seg[ticker] = (seg, name)

    print(f"实际参与评分公司: {len(stock_seg)}")

    # ── 4. 每日评分 ─────────────────────────────────────────────────────────
    print("\n正在计算每日评分...")
    trade_dates = sorted(benchmark_df["date"].tolist())

    score_records = []
    # 每5个交易日做一次调仓
    rebalance_days = 5
    rebalance_dates = trade_dates[::rebalance_days]

    for date in rebalance_dates:
        date_str = date.strftime("%Y-%m-%d")

        for ticker, (seg, name) in stock_seg.items():
            df = prices_full[ticker]
            idxs = df[df["date"] <= date].index.tolist()
            if not idxs:
                continue
            idx = idxs[-1]
            if idx < 60:
                continue

            cycle_sc = compute_cycle_score(seg)
            news_sc = get_news_score(seg, date_str, conn)
            pos_sc, pos_pct, ret_1y = compute_position_score(df, idx)
            total = compute_total_score(cycle_sc, pos_sc, news_sc)

            score_records.append({
                "date": date,
                "ticker": ticker,
                "name": name,
                "segment": seg,
                "cycle_score": cycle_sc,
                "position_score": pos_sc,
                "news_score": news_sc,
                "total_score": total,
                "price_position": pos_pct,
                "ret_1y": ret_1y,
            })

    conn.close()
    scores_df = pd.DataFrame(score_records)
    print(f"评分记录: {len(scores_df)} 条, {len(rebalance_dates)} 个调仓日")

    # ── 5. 打印评分分布 ─────────────────────────────────────────────────────
    print(f"\n评分分布:")
    print(f"  均值: {scores_df['total_score'].mean():.2f}")
    print(f"  中位数: {scores_df['total_score'].median():.2f}")
    print(f"  标准差: {scores_df['total_score'].std():.2f}")
    print(f"  最小: {scores_df['total_score'].min():.2f}")
    print(f"  最大: {scores_df['total_score'].max():.2f}")
    for q in [0.25, 0.5, 0.75, 0.9, 0.95]:
        print(f"  P{int(q*100)}: {scores_df['total_score'].quantile(q):.2f}")

    # ── 6. 分阈值回测 ───────────────────────────────────────────────────────
    thresholds = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]
    results = {}

    for threshold in thresholds:
        ts_df = scores_df[scores_df["total_score"] >= threshold].copy()
        if len(ts_df) == 0:
            print(f"\n阈值={threshold}: 无信号")
            continue

        # 基准收益
        b_ret = benchmark_df["close"].iloc[-1] / benchmark_df["close"].iloc[0] - 1

        # 模拟等权组合收益
        equity = 1.0
        equity_curve = []
        daily_rets_list = []

        for i, date in enumerate(rebalance_dates[:-1]):
            day_signals = ts_df[ts_df["date"] == date]
            next_date = rebalance_dates[i + 1]

            if len(day_signals) == 0:
                equity_curve.append({"date": next_date, "equity": equity})
                continue

            # 计算等权持有到下个调仓日的收益
            rets = []
            for _, row in day_signals.iterrows():
                t = row["ticker"]
                if t not in prices_full:
                    continue
                pdf = prices_full[t]
                cur_idxs = pdf[pdf["date"] == date].index.tolist()
                nxt_idxs = pdf[pdf["date"] == next_date].index.tolist()
                if cur_idxs and nxt_idxs:
                    cur_i = pdf.index.get_loc(cur_idxs[0])
                    nxt_i = pdf.index.get_loc(nxt_idxs[0])
                    if nxt_i > cur_i:
                        ret = pdf["close"].iloc[nxt_i] / pdf["close"].iloc[cur_i] - 1
                        rets.append(ret)

            if rets:
                period_ret = np.mean(rets)
                equity *= (1 + period_ret)
                daily_rets_list.append(period_ret)

            equity_curve.append({"date": next_date, "equity": equity})

        eq_df = pd.DataFrame(equity_curve)
        if len(eq_df) < 2:
            print(f"\n阈值={threshold}: 数据不足"); continue

        total_ret = equity - 1
        years = (eq_df["date"].iloc[-1] - eq_df["date"].iloc[0]).days / 365.0
        ann_ret = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0

        peak = np.maximum.accumulate(eq_df["equity"].values)
        dd = eq_df["equity"].values / peak - 1
        max_dd = dd.min()

        period_rets = np.array(daily_rets_list)
        if len(period_rets) > 1 and np.std(period_rets) > 0:
            sharpe = np.mean(period_rets) / np.std(period_rets) * np.sqrt(52 / rebalance_days)
        else:
            sharpe = 0.0

        win_rate = np.mean(period_rets > 0) if len(period_rets) > 0 else 0
        excess = total_ret - b_ret

        results[threshold] = {
            "total_ret": total_ret,
            "ann_ret": ann_ret,
            "max_dd": max_dd,
            "sharpe": sharpe,
            "win_rate": win_rate,
            "benchmark": b_ret,
            "excess": excess,
            "n_signals": len(ts_df),
            "n_dates": ts_df["date"].nunique(),
            "avg_pos": ts_df["price_position"].mean(),
            "avg_score": ts_df["total_score"].mean(),
        }

    # ── 7. 打印结果汇总表 ───────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print(f"{'阈值':<6}{'总收益':>8}{'年化':>8}{'最大回撤':>10}{'夏普':>7}{'胜率':>7}{'超额':>8}{'信号数':>7}{'均位置':>8}{'均评分':>7}")
    print(f"{'='*72}")
    for thr, r in sorted(results.items()):
        print(f"{thr:<6.1f}{r['total_ret']*100:>7.1f}%{r['ann_ret']*100:>7.1f}%{r['max_dd']*100:>9.1f}%{r['sharpe']:>6.2f}{r['win_rate']*100:>6.1f}%{r['excess']*100:>7.1f}%{r['n_signals']:>6}{r['avg_pos']*100:>7.0f}%{r['avg_score']:>6.2f}")
    print(f"{'='*72}")
    print(f"基准(半导体ETF):  {results[list(results.keys())[0]]['benchmark']*100 if results else 0:+.1f}%")

    # ── 8. 分析最佳阈值 ──────────────────────────────────────────────────────
    if results:
        best_sharpe = max(results.items(), key=lambda x: x[1]["sharpe"])
        best_ret = max(results.items(), key=lambda x: x[1]["total_ret"])
        print(f"\n最佳夏普: 阈值={best_sharpe[0]}, 夏普={best_sharpe[1]['sharpe']:.2f}, 收益={best_sharpe[1]['total_ret']*100:+.1f}%")
        print(f"最高收益: 阈值={best_ret[0]}, 收益={best_ret[1]['total_ret']*100:+.1f}%, 夏普={best_ret[1]['sharpe']:.2f}")

    # ── 9. 各分项贡献分析 ───────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("  各分项贡献分析（阈值=5.0 所有信号）")
    print(f"{'='*72}")
    if len(scores_df) > 0:
        avg_cycle = (scores_df["cycle_score"] * 0.4).mean()
        avg_pos = (scores_df["position_score"] * 0.3).mean()
        avg_news = (scores_df["news_score"] * 0.3).mean()
        print(f"  供需分贡献: {avg_cycle:.2f} / 4.0 (权重40%)")
        print(f"  位置分贡献: {avg_pos:.2f} / 3.0 (权重30%)")
        print(f"  新闻分贡献: {avg_news:.2f} / 3.0 (权重30%)")
        print(f"  理论总分: {avg_cycle+avg_pos+avg_news:.2f} / 10.0")

    # ── 10. 典型信号案例 ────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("  高分信号案例（综合分 >= 7.0）")
    print(f"{'='*72}")
    high_score = scores_df[scores_df["total_score"] >= 7.0].sort_values("total_score", ascending=False).head(15)
    if len(high_score) > 0:
        for _, r in high_score.iterrows():
            print(f"  {r['date'].strftime('%Y-%m-%d')} {r['ticker']} {r['name']:<8} [{r['segment']}] "
                  f"总分={r['total_score']:.2f} 供需={r['cycle_score']:.1f} 位置={r['position_score']:.1f} 新闻={r['news_score']:.1f} 位置比={r['price_position']:.0%}")
    else:
        print("  无综合分>=7.0的信号")

    return results, scores_df

if __name__ == "__main__":
    results, scores_df = run_backtest()
