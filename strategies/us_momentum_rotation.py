"""
美股三ETF动量轮动策略
SPY / QQQ / IWM 动量轮动
参数: 10日动量 / 5天调仓

参考 strategies/rotation_strategy.py 框架
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from typing import Dict, Tuple
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"


def load_us_etf_data(tickers=None, start="2019-01-01", end="2026-12-31") -> Dict[str, pd.DataFrame]:
    """加载美股ETF数据"""
    if tickers is None:
        tickers = ['SPY', 'QQQ', 'IWM']
    
    results = {}
    for t in tickers:
        fpath = CACHE_DIR / f"yahoo_{t}.pkl"
        if fpath.exists():
            df = pd.read_pickle(fpath)
            df = df[(df['date'] >= pd.to_datetime(start)) & (df['date'] <= pd.to_datetime(end))].copy()
            results[t] = df
    return results


def momentum_rotation_backtest(
    df_dict: Dict[str, pd.DataFrame],
    lookback_momentum: int = 10,
    rebalance_freq: int = 5,
    min_momentum: float = 0.0,
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    美股三ETF动量轮动回测
    
    Args:
        df_dict: {ticker: df}, 每个df需要包含 date, close 列
        lookback_momentum: 动量周期（天）
        rebalance_freq: 调仓频率（天）
        min_momentum: 最低动量阈值
    
    Returns:
        (equity_curve, benchmark_curve, metrics)
    """
    # 对齐所有日期
    all_dates = set()
    for name, df in df_dict.items():
        dates = pd.to_datetime(df["date"]).dt.date
        all_dates.update(dates)
    all_dates = sorted(all_dates)
    
    # 构建统一价格表
    price_data = {}
    for name, df in df_dict.items():
        df = df.copy()
        df["d"] = pd.to_datetime(df["date"]).dt.date
        price_data[name] = df.set_index("d")["close"]
    
    prices = pd.DataFrame(price_data).sort_index()
    prices = prices.loc[prices.index.isin(all_dates)]
    
    # 计算动量
    momentum = prices.pct_change(lookback_momentum)
    
    # 轮动回测
    initial_capital = 100000.0
    capital = initial_capital
    equity = []
    dates_list = prices.index.tolist()
    current_holder = None
    holdings = []  # 记录当前持仓
    
    for i, d in enumerate(dates_list):
        if i > 0 and i % rebalance_freq == 0:
            m = momentum.loc[d] if d in momentum.index else momentum.iloc[min(i - 1, len(momentum) - 1)]
            if m.max() > min_momentum:
                current_holder = m.idxmax()
        
        if i > 0 and current_holder is not None:
            prev_d = dates_list[i - 1]
            ret = prices.loc[d, current_holder] / prices.loc[prev_d, current_holder]
            capital *= ret
        
        equity.append(capital)
        holdings.append(current_holder if current_holder else None)
    
    equity_curve = pd.DataFrame({
        'date': pd.to_datetime(dates_list),
        'equity': equity,
        'holding': holdings,
    })
    
    # 基准：等权买入持有 (或者 SPY 买入持有)
    benchmark_ticker = 'SPY'
    if benchmark_ticker in prices.columns:
        spy_prices = prices[benchmark_ticker].values
        spy_initial = spy_prices[0]
        benchmark_equity = spy_initial / spy_initial * initial_capital * (spy_prices / spy_initial)
    else:
        # 等权
        n_etfs = len(df_dict)
        weights = np.array([1.0 / n_etfs] * n_etfs)
        first_prices = prices.iloc[0].values
        normalized = prices.values / first_prices
        weighted = normalized @ weights
        benchmark_equity = initial_capital * weighted
    
    benchmark_curve = pd.DataFrame({
        'date': pd.to_datetime(dates_list),
        'equity': benchmark_equity,
    })
    
    # 计算指标
    metrics = calc_metrics(equity_curve['equity'].values, benchmark_equity)
    
    return equity_curve, benchmark_curve, metrics


def calc_metrics(equity: np.ndarray, benchmark: np.ndarray) -> dict:
    """计算绩效指标"""
    # 总收益
    total_return = (equity[-1] - equity[0]) / equity[0]
    benchmark_return = (benchmark[-1] - benchmark[0]) / benchmark[0]
    
    # 年化收益
    n_days = len(equity)
    annual_return = (1 + total_return) ** (252 / n_days) - 1
    
    # 最大回撤
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_drawdown = drawdown.min()
    
    # 日收益
    daily_returns = np.diff(equity) / equity[:-1]
    daily_returns = np.nan_to_num(daily_returns, 0)
    
    # 夏普比率
    if daily_returns.std() > 0:
        sharpe = np.sqrt(252) * daily_returns.mean() / daily_returns.std()
    else:
        sharpe = 0
    
    # 索提诺比率
    downside = daily_returns[daily_returns < 0]
    if len(downside) > 0 and downside.std() > 0:
        sortino = np.sqrt(252) * daily_returns.mean() / downside.std()
    else:
        sortino = 0
    
    # 胜率
    win_rate = len(daily_returns[daily_returns > 0]) / max(len(daily_returns), 1)
    
    # 卡玛比率
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0
    
    return {
        'total_return': total_return,
        'annual_return': annual_return,
        'benchmark_return': benchmark_return,
        'excess_return': total_return - benchmark_return,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'win_rate': win_rate,
        'calmar_ratio': calmar,
        'final_equity': equity[-1],
        'n_days': n_days,
    }


def print_report(metrics: dict, strategy_name: str = "美股三ETF动量轮动"):
    """打印回测报告"""
    print(f"\n{'='*55}")
    print(f"  回测报告: {strategy_name}")
    print(f"  参数: 10日动量 / 5天调仓")
    print(f"{'='*55}")
    print(f"  {'总收益率':>15}: {metrics['total_return']*100:>8.2f}%")
    print(f"  {'年化收益率':>15}: {metrics['annual_return']*100:>8.2f}%")
    print(f"  {'基准收益':>15}: {metrics['benchmark_return']*100:>8.2f}%")
    print(f"  {'超额收益':>15}: {metrics['excess_return']*100:>8.2f}%")
    print(f"  {'最大回撤':>15}: {metrics['max_drawdown']*100:>8.2f}%")
    print(f"  {'夏普比率':>15}: {metrics['sharpe_ratio']:>8.2f}")
    print(f"  {'索提诺比率':>15}: {metrics['sortino_ratio']:>8.2f}")
    print(f"  {'卡玛比率':>15}: {metrics['calmar_ratio']:>8.2f}")
    print(f"  {'胜率':>15}: {metrics['win_rate']*100:>8.2f}%")
    print(f"  {'最终资金':>15}: {metrics['final_equity']:>10.2f}")
    print(f"  {'交易天数':>15}: {metrics['n_days']:>8}")
    print(f"{'='*55}")


def plot_equity_curve(
    equity_curve: pd.DataFrame,
    benchmark_curve: pd.DataFrame,
    output_path: Path = None,
) -> go.Figure:
    """生成equity curve图"""
    fig = go.Figure()
    
    # 策略曲线
    fig.add_trace(go.Scatter(
        x=equity_curve['date'],
        y=equity_curve['equity'],
        mode='lines',
        name='动量轮动策略',
        line=dict(color='#2196F3', width=2),
    ))
    
    # 基准曲线
    fig.add_trace(go.Scatter(
        x=benchmark_curve['date'],
        y=benchmark_curve['equity'],
        mode='lines',
        name='SPY买入持有',
        line=dict(color='#9E9E9E', width=1.5, dash='dash'),
    ))
    
    fig.update_layout(
        title='美股三ETF动量轮动策略 (SPY/QQQ/IWM) — Equity Curve',
        xaxis_title='日期',
        yaxis_title='资金',
        template='plotly_white',
        hovermode='x unified',
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        width=1100,
        height=600,
    )
    
    fig.update_yaxes(
        tickformat=",.0f",
        gridcolor="#F0F0F0",
    )
    
    fig.update_xaxes(
        gridcolor="#F0F0F0",
    )
    
    if output_path:
        fig.write_image(output_path, scale=2)
        print(f"[Saved] Equity curve -> {output_path}")
    
    return fig


def run_backtest():
    """运行完整的回测"""
    print("\n" + "="*60)
    print("  美股三ETF动量轮动策略回测")
    print("  SPY / QQQ / IWM  |  10日动量 / 5天调仓")
    print("="*60)
    
    # 加载数据
    df_dict = load_us_etf_data(['SPY', 'QQQ', 'IWM'])
    
    if len(df_dict) < 3:
        print("[Error] 数据不足，请先运行 python data/yahoo_us.py --all")
        return
    
    print(f"\n数据范围:")
    for name, df in df_dict.items():
        print(f"  {name}: {df['date'].min().date()} ~ {df['date'].max().date()}, {len(df)} 个交易日")
    
    # 运行回测
    equity_curve, benchmark_curve, metrics = momentum_rotation_backtest(
        df_dict,
        lookback_momentum=10,
        rebalance_freq=5,
    )
    
    # 打印报告
    print_report(metrics)
    
    # 生成图表
    output_path = CACHE_DIR / "us_momentum_rotation_equity.png"
    fig = plot_equity_curve(equity_curve, benchmark_curve, output_path)
    
    return equity_curve, benchmark_curve, metrics, fig


if __name__ == "__main__":
    run_backtest()
