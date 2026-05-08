#!/usr/bin/env python3
"""
Web监控面板 - Flask + Plotly
功能:
- 策略回测结果可视化
- 权益曲线对比
- 回撤曲线
- 交易记录表

启动: python scripts/dashboard.py
访问: http://localhost:8050
"""

import sys
sys.path.insert(0, "/Users/tanwei/quant-trading")

from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import numpy as np
from datetime import datetime

from data.fetcher import fetch_etf
from strategies.trend import MA_Cross, MACD_Strat, Breakout_20
from strategies.mean_reversion import RSI_Strat, BollingerBand
from backtest.engine import BacktestEngine
from backtest.risk import BacktestEngineV2, PositionConfig

app = Flask(__name__)

# ============================================================
# 全局缓存（避免重复回测）
# ============================================================
_cache = {}


def run_backtest(symbol, strategy, with_risk=False):
    """运行回测并缓存结果"""
    key = f"{symbol}_{strategy}_{with_risk}"
    if key in _cache:
        return _cache[key]

    df = fetch_etf(symbol, "20230101", "20241231")
    if len(df) < 50:
        return None

    strats = {
        "MA(5,20)": MA_Cross(5, 20),
        "MA(10,60)": MA_Cross(10, 60),
        "MACD": MACD_Strat(),
        "Breakout": Breakout_20(20),
        "RSI": RSI_Strat(14),
        "BB": BollingerBand(20, 2.0),
    }
    strat = strats.get(strategy)
    if not strat:
        return None

    signals = strat.generate(df)

    if with_risk:
        cfg = PositionConfig(base_ratio=0.8, stop_loss=0.07,
                            trailing_stop=True, trailing_pct=0.05)
        engine = BacktestEngineV2(initial_capital=100_000, risk_config=cfg)
    else:
        engine = BacktestEngine(initial_capital=100_000)

    result = engine.run(df, signals)
    m = result["metrics"]

    # 权益曲线
    eq = result["equity_curve"]
    equity_curve = {
        "date": [str(d) for d in eq["date"].tolist()],
        "equity": eq["equity"].tolist(),
        "benchmark": eq["benchmark"].tolist(),
        "drawdown": ((eq["equity"] / np.maximum.accumulate(eq["equity"])) - 1).tolist(),
    }

    # 交易记录
    trades = result["trades"][-20:]  # 最近20笔

    data = {
        "strategy": strategy,
        "symbol": symbol,
        "with_risk": with_risk,
        "metrics": {
            "total_return": f"{m['total_return']*100:.2f}%",
            "annual_return": f"{m['annual_return']*100:.2f}%",
            "max_drawdown": f"{m['max_drawdown']*100:.2f}%",
            "sharpe_ratio": f"{m['sharpe_ratio']:.2f}",
            "num_trades": m["num_trades"],
            "win_rate": f"{m['win_rate']*100:.1f}%",
        },
        "equity_curve": equity_curve,
        "trades": trades,
    }

    _cache[key] = data
    return data


# ============================================================
# HTML模板
# ============================================================

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>量化交易监控面板</title>
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
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }
        .card { background: #1a1d27; border-radius: 10px; padding: 16px; border: 1px solid #2a2d3a; }
        .card-title { color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
        .card-value { color: #fff; font-size: 1.6em; font-weight: bold; }
        .card-value.positive { color: #4ade80; }
        .card-value.negative { color: #f87171; }
        .chart { background: #1a1d27; border-radius: 10px; padding: 16px; border: 1px solid #2a2d3a; margin-bottom: 20px; }
        .chart-title { color: #888; font-size: 12px; text-transform: uppercase; margin-bottom: 12px; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; color: #666; font-size: 11px; text-transform: uppercase;
              padding: 8px; border-bottom: 1px solid #2a2d3a; }
        td { padding: 8px; font-size: 13px; border-bottom: 1px solid #1e2230; }
        .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
        .tag-buy { background: #1a4d2e; color: #4ade80; }
        .tag-sell { background: #4d1a1a; color: #f87171; }
        .empty { color: #555; text-align: center; padding: 40px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 量化交易监控面板</h1>
        <div class="controls">
            <select id="symbol">
                <option value="510300">沪深300ETF</option>
                <option value="510500">中证500ETF</option>
                <option value="159915">创业板ETF</option>
            </select>
            <select id="strategy">
                <option value="MA(5,20)">均线交叉(5,20)</option>
                <option value="MA(10,60)">均线交叉(10,60)</option>
                <option value="MACD">MACD</option>
                <option value="Breakout">突破策略</option>
                <option value="RSI">RSI</option>
                <option value="BB">布林带</option>
            </select>
            <label style="color:#888;font-size:13px;">
                <input type="checkbox" id="withRisk"> 带风控
            </label>
            <button onclick="runBacktest()">回测</button>
        </div>
    </div>

    <div id="metrics" class="grid"></div>

    <div id="equityChart" class="chart">
        <div class="chart-title">权益曲线 vs 基准</div>
        <div id="equityPlot"></div>
    </div>

    <div id="drawdownChart" class="chart">
        <div class="chart-title">回撤曲线</div>
        <div id="drawdownPlot"></div>
    </div>

    <div class="chart">
        <div class="chart-title">最近交易记录</div>
        <div id="tradesTable"></div>
    </div>

    <script>
    function runBacktest() {
        const symbol = document.getElementById('symbol').value;
        const strategy = document.getElementById('strategy').value;
        const withRisk = document.getElementById('withRisk').checked;

        fetch(`/api/backtest?symbol=${symbol}&strategy=${strategy}&risk=${withRisk}`)
            .then(r => r.json())
            .then(data => {
                if (!data || !data.metrics) {
                    document.getElementById('metrics').innerHTML = '<div class="empty">无数据</div>';
                    return;
                }
                renderMetrics(data);
                renderEquityCurve(data.equity_curve);
                renderTrades(data.trades);
            });
    }

    function renderMetrics(d) {
        const m = d.metrics;
        const ret = parseFloat(m.total_return);
        const html = `
            <div class="card">
                <div class="card-title">总收益率</div>
                <div class="card-value ${ret>=0?'positive':'negative'}">${m.total_return}</div>
            </div>
            <div class="card">
                <div class="card-title">年化收益率</div>
                <div class="card-value ${parseFloat(m.annual_return)>=0?'positive':'negative'}">${m.annual_return}</div>
            </div>
            <div class="card">
                <div class="card-title">最大回撤</div>
                <div class="card-value negative">${m.max_drawdown}</div>
            </div>
            <div class="card">
                <div class="card-title">夏普比率</div>
                <div class="card-value ${parseFloat(m.sharpe_ratio)>=0?'positive':'negative'}">${m.sharpe_ratio}</div>
            </div>
            <div class="card">
                <div class="card-title">交易次数</div>
                <div class="card-value">${m.num_trades}</div>
            </div>
            <div class="card">
                <div class="card-title">胜率</div>
                <div class="card-value">${m.win_rate}</div>
            </div>
        `;
        document.getElementById('metrics').innerHTML = html;
    }

    function renderEquityCurve(eq) {
        const trace1 = { x: eq.date, y: eq.equity, name: '策略', type: 'scatter', line: {color: '#4ade80'} };
        const trace2 = { x: eq.date, y: eq.benchmark, name: '基准', type: 'scatter', line: {color: '#888'} };
        Plotly.newPlot('equityPlot', [trace1, trace2], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: {color: '#888'},
            margin: {t:10,l:50,r:20,b:30},
            xaxis: {gridcolor: '#222', zerolinecolor: '#333'},
            yaxis: {gridcolor: '#222', zerolinecolor: '#333'},
        });

        const trace3 = { x: eq.date, y: eq.drawdown.map(v=>v*100), name: '回撤', type: 'scatter',
                         fill: 'tozeroy', line: {color: '#f87171'}, fillcolor: 'rgba(248,113,113,0.1)' };
        Plotly.newPlot('drawdownPlot', [trace3], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: {color: '#888'},
            margin: {t:10,l:50,r:20,b:30},
            xaxis: {gridcolor: '#222', zerolinecolor: '#333'},
            yaxis: {gridcolor: '#222', zerolinecolor: '#333'},
        });
    }

    function renderTrades(trades) {
        if (!trades || trades.length === 0) {
            document.getElementById('tradesTable').innerHTML = '<div class="empty">暂无交易记录</div>';
            return;
        }
        let html = '<table><tr><th>日期</th><th>方向</th><th>价格</th></tr>';
        for (const t of trades.slice(-10).reverse()) {
            html += `<tr><td>${t.date}</td>
                     <td><span class="tag ${t.action==='BUY'?'tag-buy':'tag-sell'}">${t.action}</span></td>
                     <td>${parseFloat(t.price).toFixed(3)}</td></tr>`;
        }
        html += '</table>';
        document.getElementById('tradesTable').innerHTML = html;
    }

    // 默认加载
    runBacktest();
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(TEMPLATE)


@app.route("/api/backtest")
def api_backtest():
    symbol = request.args.get("symbol", "510300")
    strategy = request.args.get("strategy", "MA(5,20)")
    with_risk = request.args.get("risk", "false").lower() == "true"

    data = run_backtest(symbol, strategy, with_risk)
    return jsonify(data)


if __name__ == "__main__":
    print("=" * 50)
    print("  量化交易监控面板")
    print("  http://localhost:8050")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8050, debug=False)
