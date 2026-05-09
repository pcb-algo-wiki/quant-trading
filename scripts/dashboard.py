#!/usr/bin/env python3
"""
量化交易监控面板 v2.0
=====================
增强功能：
- 多策略权益曲线对比（MA / Rotation / Multi-factor）
- 当前持仓状态（PaperTrader数据）
- 今日策略信号面板
- 市场环境指示（牛/熊/震荡）
- 实时权益快照

启动: .venv/bin/python scripts/dashboard.py
访问: http://localhost:8050
"""

import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")

import json
import logging
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import numpy as np

from data.fetcher import fetch_etf
from strategies.ma_optimized import MAOptimizedStrategy
from strategies.rotation_strategy import RotationStrategy
from strategies.multi_factor import MultiFactorStrategy
from backtest.engine import BacktestEngine
from utils.config import cfg

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 全局缓存
# ============================================================
_cache = {}
_equity_curves = {}   # 多策略对比数据
_positions = {}       # 当前持仓


def _load_positions():
    """加载PaperTrader持仓数据"""
    p = Path("/Users/tanwei/quant-trading/results/paper_trades.json")
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def _run_strategy_backtest(symbol: str, days: int = 500) -> dict | None:
    """运行单策略回测并返回权益曲线"""
    end = datetime.now().strftime("%Y%m%d")
    start_dt = pd.Timestamp(end) - pd.Timedelta(days=days)
    start = start_dt.strftime("%Y%m%d")

    df = fetch_etf(symbol, start, end)
    if len(df) < 60:
        return None

    return df


def _ma_signal(df: pd.DataFrame, etfs: dict) -> dict:
    """计算各ETF的MA信号"""
    results = {}
    for code, info in etfs.items():
        if not info.get("enabled"):
            continue
        df_etf = fetch_etf(code, "20240101", datetime.now().strftime("%Y%m%d"))
        if len(df_etf) < 25:
            continue
        fast = cfg.get(f"optimal_params.cyb_ma_fast" if "159915" in code
                       else f"optimal_params.zz500_ma_fast" if "510500" in code
                       else "optimal_params.hs300_ma_fast")
        slow = cfg.get(f"optimal_params.cyb_ma_slow" if "159915" in code
                       else f"optimal_params.zz500_ma_slow" if "510500" in code
                       else "optimal_params.hs300_ma_slow")
        ma_fast = df_etf["close"].rolling(fast).mean()
        ma_slow = df_etf["close"].rolling(slow).mean()
        latest = len(df_etf) - 1
        diff = ma_fast.iloc[latest] - ma_slow.iloc[latest]
        prev_diff = ma_fast.iloc[latest - 1] - ma_slow.iloc[latest - 1]
        price = df_etf["close"].iloc[-1]
        results[code] = {
            "name": info["name"],
            "price": round(price, 3),
            "ma_fast": round(ma_fast.iloc[latest], 3),
            "ma_slow": round(ma_slow.iloc[latest], 3),
            "signal": "BUY" if diff > 0 and prev_diff <= 0 else "SELL" if diff < 0 and prev_diff >= 0 else "HOLD",
            "trend": "上升" if diff > 0 else "下降",
        }
    return results


def _rotation_signal(df_dict: dict) -> dict:
    """计算轮动策略信号"""
    if len(df_dict) < 3:
        return {}
    strat = RotationStrategy(lookback_momentum=10, rebalance_freq=5)
    try:
        results = strat.generate(df_dict)
        latest_date = max(r["date"].max() for r in results.values())
        signals = {}
        for name, df_r in results.items():
            row = df_r[df_r["date"] == latest_date].iloc[-1]
            signals[name] = {
                "position": "持仓" if row["position"] == 1 else "空仓",
                "momentum": round(row["momentum"] * 100, 2) if pd.notna(row["momentum"]) else 0,
            }
        return signals
    except Exception:
        return {}


def _market_environment(df: pd.DataFrame) -> dict:
    """判断市场环境"""
    if len(df) < 60:
        return {"regime": "unknown", "trend": "unknown", "volatility": "unknown"}

    close = df["close"]
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    volatility = close.rolling(20).std() / close.rolling(20).mean()

    latest = len(df) - 1
    price = close.iloc[latest]
    m20 = ma20.iloc[latest]
    m60 = ma60.iloc[latest]
    vol = volatility.iloc[latest]

    # 趋势判断
    if price > m20 and m20 > m60:
        trend = "牛市"
    elif price < m20 and m20 < m60:
        trend = "熊市"
    else:
        trend = "震荡"

    # 波动率
    vol_pct = vol * 100
    if vol_pct < 1.0:
        vol_level = "低波动"
    elif vol_pct < 2.0:
        vol_level = "正常"
    else:
        vol_level = "高波动"

    # 近期表现
    ret_5d = (close.iloc[latest] / close.iloc[max(0, latest - 5)] - 1) * 100
    ret_20d = (close.iloc[latest] / close.iloc[max(0, latest - 20)] - 1) * 100

    return {
        "regime": trend,
        "volatility": vol_level,
        "vol_pct": round(vol_pct, 2),
        "ret_5d": round(ret_5d, 2),
        "ret_20d": round(ret_20d, 2),
        "ma20": round(m20, 3),
        "ma60": round(m60, 3),
    }


def _build_equity_curves():
    """预计算多策略权益曲线"""
    global _equity_curves

    symbols = ["159915", "510500", "510300"]
    end = datetime.now().strftime("%Y%m%d")
    start = "20240101"

    dfs = {}
    for sym in symbols:
        df = fetch_etf(sym, start, end)
        if len(df) >= 60:
            dfs[sym] = df

    if not dfs:
        return

    # 1. MA优化策略
    curves = {}
    for sym, df in dfs.items():
        strat_name = f"MA_{sym}"
        try:
            fast = cfg.get(f"optimal_params.cyb_ma_fast" if sym == "159915"
                           else f"optimal_params.zz500_ma_fast" if sym == "510500"
                           else "optimal_params.hs300_ma_fast")
            slow = cfg.get(f"optimal_params.cyb_ma_slow" if sym == "159915"
                           else f"optimal_params.zz500_ma_slow" if sym == "510500"
                           else "optimal_params.hs300_ma_slow")
            strat = MAOptimizedStrategy(fast, slow)
            signals = strat.generate(df.copy())
            engine = BacktestEngine(initial_capital=100_000)
            result = engine.run(df, signals)
            eq = result["equity_curve"]
            curves[sym] = {
                "dates": [str(d) for d in eq["date"].tolist()],
                "equity": eq["equity"].tolist(),
                "benchmark": eq["benchmark"].tolist(),
            }
        except Exception as e:
            logger.warning(f"MA strategy failed for {sym}: {e}")

    # 2. 轮动策略
    try:
        strat = RotationStrategy(lookback_momentum=10, rebalance_freq=5)
        results = strat.generate(dfs)
        # 取第一个ETF的权益曲线（等权）
        if results:
            first_key = list(results.keys())[0]
            eq_dates = results[first_key]["date"].tolist()
            # 合并三个ETF的等权组合
            combined_equity = []
            for i in range(len(eq_dates)):
                total = 0
                count = 0
                for name, res in results.items():
                    if len(res) > i and res["position"].iloc[i] == 1:
                        total += res["close"].iloc[i]
                        count += 1
                if count > 0:
                    if len(combined_equity) > 0:
                        prev = combined_equity[-1]
                        price_now = total / count
                        # 用收盘价计算每日收益
                        prev_total = 0
                        prev_count = 0
                        for name, res in results.items():
                            if len(res) > max(0, i-1) and res["position"].iloc[max(0, i-1)] == 1:
                                prev_total += res["close"].iloc[max(0, i-1)]
                                prev_count += 1
                        if prev_count > 0:
                            price_prev = prev_total / prev_count
                            combined_equity.append(prev * (price_now / price_prev))
                        else:
                            combined_equity.append(prev)
                    else:
                        combined_equity.append(100000.0)
                else:
                    combined_equity.append(combined_equity[-1] if combined_equity else 100000.0)

            curves["rotation"] = {
                "dates": [str(d) for d in eq_dates],
                "equity": combined_equity,
            }
    except Exception as e:
        logger.warning(f"Rotation strategy failed: {e}")

    _equity_curves = curves


# ============================================================
# HTML模板
# ============================================================

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>量化交易监控面板 v2</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0f1117; color: #e0e0e0; padding: 20px; }
        h1 { color: #fff; margin-bottom: 20px; font-size: 1.4em; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .controls { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
        select, button { background: #1e2230; color: #e0e0e0; border: 1px solid #333;
                        padding: 8px 14px; border-radius: 6px; font-size: 14px; cursor: pointer; }
        button { background: #2d5a8a; border: none; }
        button:hover { background: #3d7ab8; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
        .card { background: #1a1d27; border-radius: 10px; padding: 14px; border: 1px solid #2a2d3a; }
        .card-title { color: #666; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
        .card-value { color: #fff; font-size: 1.5em; font-weight: bold; }
        .card-value.positive { color: #4ade80; }
        .card-value.negative { color: #f87171; }
        .card-value.neutral { color: #fbbf24; }
        .chart { background: #1a1d27; border-radius: 10px; padding: 14px; border: 1px solid #2a2d3a; margin-bottom: 16px; }
        .chart-title { color: #666; font-size: 11px; text-transform: uppercase; margin-bottom: 10px; }
        .signal-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 16px; }
        .signal-card { background: #1a1d27; border-radius: 10px; padding: 14px; border: 1px solid #2a2d3a; }
        .signal-name { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
        .signal-row { display: flex; justify-content: space-between; font-size: 12px; margin: 4px 0; color: #888; }
        .signal-row span:last-child { color: #ccc; }
        .signal-badge { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; }
        .badge-buy { background: #1a4d2e; color: #4ade80; }
        .badge-sell { background: #4d1a1a; color: #f87171; }
        .badge-hold { background: #3d3a1a; color: #fbbf24; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; color: #555; font-size: 11px; text-transform: uppercase;
              padding: 8px; border-bottom: 1px solid #2a2d3a; }
        td { padding: 8px; font-size: 13px; border-bottom: 1px solid #1e2230; }
        .pos-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
        .pos-long { background: #1a4d2e; color: #4ade80; }
        .pos-empty { background: #2a2d3a; color: #666; }
        .empty { color: #444; text-align: center; padding: 30px; font-size: 13px; }
        .section-title { color: #444; font-size: 11px; text-transform: uppercase; margin: 16px 0 8px; padding-left: 4px; }
        .market-banner { background: linear-gradient(135deg, #1a1d27 0%, #2a2040 100%); border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; border: 1px solid #3a3a5a; display: flex; gap: 30px; align-items: center; }
        .market-badge { font-size: 1.8em; font-weight: 800; }
        .market-info { flex: 1; }
        .market-regime { color: #fff; font-size: 1.1em; font-weight: 600; }
        .market-detail { color: #888; font-size: 12px; margin-top: 4px; }
        .refresh-time { color: #444; font-size: 11px; text-align: right; }
        .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
        .legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #888; }
        .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 量化交易监控面板 v2</h1>
        <div>
            <button onclick="refreshAll()">🔄 刷新</button>
        </div>
    </div>

    <div class="market-banner" id="marketBanner">
        <div class="market-badge" id="marketEmoji">⏳</div>
        <div class="market-info">
            <div class="market-regime" id="marketRegime">加载中...</div>
            <div class="market-detail" id="marketDetail"></div>
        </div>
        <div class="refresh-time" id="refreshTime"></div>
    </div>

    <div class="grid" id="accountMetrics"></div>

    <div class="signal-grid" id="maSignals"></div>

    <div class="chart">
        <div class="chart-title">多策略权益曲线对比</div>
        <div class="legend" id="chartLegend"></div>
        <div id="equityPlot" style="height: 320px;"></div>
    </div>

    <div class="chart">
        <div class="chart-title">当前持仓</div>
        <div id="positionsTable"></div>
    </div>

    <div class="chart">
        <div class="chart-title">最近成交记录</div>
        <div id="tradesTable"></div>
    </div>

    <script>
    const COLORS = ['#4ade80', '#60a5fa', '#f472b6', '#fbbf24', '#a78bfa', '#34d399'];
    const STRAT_NAMES = {'159915': '创业板MA', '510500': '中证500MA', '510300': '沪深300MA', 'rotation': '三ETF轮动'};

    function refreshAll() {
        Promise.all([
            fetch('/api/market').then(r => r.json()),
            fetch('/api/positions').then(r => r.json()),
            fetch('/api/equity_curves').then(r => r.json()),
            fetch('/api/ma_signals').then(r => r.json()),
        ]).then(([market, positions, curves, maSignals]) => {
            renderMarket(market);
            renderAccount(positions);
            renderEquityCurves(curves);
            renderMASignals(maSignals);
            renderPositions(positions);
            renderTrades(positions);
            document.getElementById('refreshTime').textContent = '更新: ' + new Date().toLocaleTimeString('zh-CN');
        });
    }

    function renderMarket(m) {
        const emoji = m.regime === '牛市' ? '🐂' : m.regime === '熊市' ? '🐻' : '🔄';
        const regimeColor = m.regime === '牛市' ? '#4ade80' : m.regime === '熊市' ? '#f87171' : '#fbbf24';
        document.getElementById('marketEmoji').textContent = emoji;
        document.getElementById('marketRegime').textContent = m.regime || '未知';
        document.getElementById('marketRegime').style.color = regimeColor;
        document.getElementById('marketDetail').innerHTML =
            `波动率: ${m.volatility} (${m.vol_pct}%) | 5日: ${m.ret_5d}% | 20日: ${m.ret_20d}%`;
    }

    function renderAccount(p) {
        const stats = p.stats || {};
        const eq = stats.current_equity || 0;
        const ret = parseFloat(stats.total_return || 0);
        const retStr = typeof stats.total_return_pct === 'string' ? stats.total_return_pct : (ret * 100).toFixed(2) + '%';
        const html = `
            <div class="card"><div class="card-title">当前权益</div><div class="card-value">¥${eq.toLocaleString('zh-CN', {minimumFractionDigits: 2})}</div></div>
            <div class="card"><div class="card-title">总收益率</div><div class="card-value ${ret>=0?'positive':'negative'}">${retStr}</div></div>
            <div class="card"><div class="card-title">持仓数</div><div class="card-value">${stats.num_positions || 0}</div></div>
            <div class="card"><div class="card-title">成交单数</div><div class="card-value">${stats.num_trades || 0}</div></div>
            <div class="card"><div class="card-title">胜率</div><div class="card-value ${(stats.win_rate||0)>=0.5?'positive':'negative'}">${((stats.win_rate||0)*100).toFixed(1)}%</div></div>
            <div class="card"><div class="card-title">挂单数</div><div class="card-value neutral">${stats.pending_orders || 0}</div></div>
        `;
        document.getElementById('accountMetrics').innerHTML = html;
    }

    function renderEquityCurves(c) {
        if (!c || Object.keys(c).length === 0) {
            document.getElementById('equityPlot').innerHTML = '<div class="empty">暂无数据</div>';
            return;
        }
        const traces = [];
        const names = [];
        let i = 0;
        for (const [key, d] of Object.entries(c)) {
            if (!d.dates || d.dates.length === 0) continue;
            const norm = [];
            const base = d.equity[0] || 1;
            for (const v of d.equity) {
                norm.push((v / base - 1) * 100);
            }
            traces.push({
                x: d.dates, y: norm, name: STRAT_NAMES[key] || key,
                type: 'scatter', line: {color: COLORS[i % COLORS.length], width: 2}
            });
            names.push({name: STRAT_NAMES[key] || key, color: COLORS[i % COLORS.length]});
            i++;
        }
        // 基准线
        traces.push({
            x: ['2024-01-01', new Date().toISOString().slice(0,10)],
            y: [0, 0], name: '基准', type: 'scatter',
            line: {color: '#333', width: 1, dash: 'dot'}
        });

        document.getElementById('chartLegend').innerHTML = names.map(n =>
            `<div class="legend-item"><div class="legend-dot" style="background:${n.color}"></div>${n.name}</div>`
        ).join('');

        Plotly.newPlot('equityPlot', traces, {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: {color: '#888', size: 11},
            margin: {t:10,l:50,r:20,b:30},
            xaxis: {gridcolor: '#1e2230', zerolinecolor: '#222', showgrid: true},
            yaxis: {gridcolor: '#1e2230', zerolinecolor: '#222', showgrid: true, tickformat: '.0f', tick suffix: '%'},
            legend: {orientation: 'h', y: 1.12, x: 0.5, xanchor: 'center'},
            hovermode: 'x unified',
        }, {responsive: true});
    }

    function renderMASignals(signals) {
        if (!signals || Object.keys(signals).length === 0) {
            document.getElementById('maSignals').innerHTML = '<div class="empty">暂无信号</div>';
            return;
        }
        const badgeClass = {BUY: 'badge-buy', SELL: 'badge-sell', HOLD: 'badge-hold'};
        let html = '';
        for (const [code, s] of Object.entries(signals)) {
            html += `
            <div class="signal-card">
                <div class="signal-name">${s.name} (${code})</div>
                <div style="margin-bottom:6px">
                    <span class="signal-badge ${badgeClass[s.signal]||'badge-hold'}">${s.signal}</span>
                    <span style="color:#888;font-size:11px;margin-left:8px">${s.trend}</span>
                </div>
                <div class="signal-row"><span>现价</span><span>${s.price}</span></div>
                <div class="signal-row"><span>MA${s.ma_fast.toString().includes('15')?'(15)':s.ma_fast.toString().includes('5')?'(5)':'(3)'}/MA${s.ma_slow.toString().includes('20')?'(20)':''}</span><span>${s.ma_fast} / ${s.ma_slow}</span></div>
            </div>`;
        }
        document.getElementById('maSignals').innerHTML = html;
    }

    function renderPositions(p) {
        const pos = p.positions || [];
        if (pos.length === 0) {
            document.getElementById('positionsTable').innerHTML = '<div class="empty">暂无持仓（模拟账户空仓）</div>';
            return;
        }
        let html = '<table><tr><th>ETF</th><th>股数</th><th>成本价</th><th>现价</th><th>市值</th><th>浮动盈亏</th><th>收益率</th></tr>';
        for (const item of pos) {
            const pnl = item.unrealized_pnl || 0;
            const pct = item.return_pct || 0;
            html += `<tr>
                <td><span class="pos-tag pos-long">${item.symbol}</span></td>
                <td>${item.shares}</td>
                <td>${item.avg_cost}</td>
                <td>${item.current_price}</td>
                <td>¥${(item.market_value||0).toLocaleString('zh-CN',{minimumFractionDigits:2})}</td>
                <td style="color:${pnl>=0?'#4ade80':'#f87171'}">${pnl>=0?'+':''}${pnl.toFixed(2)}</td>
                <td style="color:${pct>=0?'#4ade80':'#f87171'}">${pct>=0?'+':''}${(pct*100).toFixed(2)}%</td>
            </tr>`;
        }
        html += '</table>';
        document.getElementById('positionsTable').innerHTML = html;
    }

    function renderTrades(p) {
        const trades = (p.trades || []).slice(-10).reverse();
        if (trades.length === 0) {
            document.getElementById('tradesTable').innerHTML = '<div class="empty">暂无成交记录</div>';
            return;
        }
        let html = '<table><tr><th>日期</th><th>方向</th><th>ETF</th><th>价格</th><th>股数</th><th>盈亏</th></tr>';
        for (const t of trades) {
            const side = t.side.includes('BUY') ? '买入' : '卖出';
            const sideClass = t.side.includes('BUY') ? 'pos-long' : 'badge-sell';
            html += `<tr>
                <td>${t.date}</td>
                <td><span class="pos-tag ${sideClass}">${side}</span></td>
                <td>${t.symbol}</td>
                <td>${parseFloat(t.price).toFixed(3)}</td>
                <td>${t.shares}</td>
                <td style="color:${(t.pnl||0)>=0?'#4ade80':'#f87171'}">${(t.pnl||0)>=0?'+':''}${(t.pnl||0).toFixed(2)}</td>
            </tr>`;
        }
        html += '</table>';
        document.getElementById('tradesTable').innerHTML = html;
    }

    // 初始化
    refreshAll();
    // 每5分钟自动刷新
    setInterval(refreshAll, 5 * 60 * 1000);
    </script>
</body>
</html>
"""


# ============================================================
# API路由
# ============================================================

@app.route("/")
def index():
    return render_template_string(TEMPLATE)


@app.route("/api/market")
def api_market():
    """市场环境"""
    sym = "159915"  # 用创业板指数
    df = fetch_etf(sym, "20240101", datetime.now().strftime("%Y%m%d"))
    if df is None or len(df) < 60:
        return jsonify({"regime": "unknown", "volatility": "unknown", "vol_pct": 0, "ret_5d": 0, "ret_20d": 0})
    return jsonify(_market_environment(df))


@app.route("/api/positions")
def api_positions():
    """当前持仓"""
    data = _load_positions()
    return jsonify(data if data else {"stats": {}, "positions": [], "trades": []})


@app.route("/api/equity_curves")
def api_equity_curves():
    """多策略权益曲线"""
    if not _equity_curves:
        _build_equity_curves()
    return jsonify(_equity_curves)


@app.route("/api/ma_signals")
def api_ma_signals():
    """MA策略信号"""
    try:
        etfs = cfg.etfs
        signals = _ma_signal(None, etfs)
        return jsonify(signals)
    except Exception as e:
        logger.warning(f"MA signals error: {e}")
        return jsonify({})


@app.route("/api/refresh_curves", methods=["POST"])
def api_refresh_curves():
    """强制刷新权益曲线"""
    global _equity_curves
    _equity_curves = {}
    _build_equity_curves()
    return jsonify({"status": "ok", "keys": list(_equity_curves.keys())})


if __name__ == "__main__":
    print("=" * 50)
    print("  量化监控面板 v2.0")
    print("  http://localhost:8050")
    print("=" * 50)
    # 预热权益曲线
    print("预计算多策略权益曲线...")
    _build_equity_curves()
    print(f"加载了 {len(_equity_curves)} 条策略曲线")
    app.run(host="0.0.0.0", port=8050, debug=False)
