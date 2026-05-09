"""
strategies/covered_call.py
===========================
备兑期权策略（Covered Call Writing）

原理：
- 持有标的（ETF/股票）的同时，卖出同等数量OTM看涨期权
- 收取权利金，增强投资组合收益
- 代价：上涨时持仓收益被"转让"给买方（天花板收益）

适用场景：
- 低波动率/震荡市：权利金收入显著
- 持股不涨时：期权费补贴机会成本
- 熊市初期：部分对冲下行风险

数据说明：
- A股期权历史数据不可用（akshare被代理拦截）
- 模拟方式：用Black-Scholes + 近似隐波估算期权价格
- 实际操作前需用真实经纪商接口获取期权链

使用方式:
    from strategies.covered_call import CoveredCallStrategy
    from backtest.engine import BacktestEngine

    strategy = CoveredCallStrategy('510300', strike_pct=0.05, dte=30)
    engine = BacktestEngine(initial_capital=100000)
    result = engine.run(strategy, start='20200101', end='20260101')
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, Literal
from scipy.stats import norm

# ─── Black-Scholes 定价 ───────────────────────────────────────────────────────

def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Black-Scholes 欧式看涨期权定价

    Args:
        S: 标的当前价格
        K: 行权价
        T: 到期时间（年）
        r: 无风险利率
        sigma: 波动率（年化）
    """
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes 欧式看跌期权定价"""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float) -> dict:
    """
    计算期权Greeks（Delta, Gamma, Vega, Theta, Rho）
    T 以年为单位
    """
    if T <= 1e-6 or sigma <= 0:
        return {'delta': 1 if S > K else 0, 'gamma': 0, 'vega': 0, 'theta': 0, 'rho': 0}

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    delta = norm.cdf(d1)
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * norm.pdf(d1) * np.sqrt(T)
    theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
             - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
    rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100

    return {
        'delta': delta,
        'gamma': gamma,
        'vega': vega,
        'theta': theta,   # 每日时间损耗
        'rho': rho,
    }


# ─── 隐含波动率估算（简化版） ────────────────────────────────────────────────

def estimate_iv_from_returns(returns: pd.Series, annualize: bool = True) -> float:
    """
    从历史收益率估算隐含波动率（作为IV近似）

    Args:
        returns: 日收益率序列
        annualize: 是否年化（×sqrt(252)）

    Returns:
        年化波动率
    """
    if len(returns) < 20:
        return 0.20  # 默认20%波动率

    daily_vol = returns.std()
    if annualize:
        return daily_vol * np.sqrt(252)
    return daily_vol


def estimate_iv_from_price_history(prices: pd.Series, lookback: int = 20) -> float:
    """
    从价格历史估算波动率（用于期权定价）

    使用最近N日收益率的标准差作为波动率代理
    """
    if len(prices) < lookback + 1:
        return 0.20

    recent = prices.iloc[-lookback:]
    returns = recent.pct_change().dropna()
    return estimate_iv_from_returns(returns)


# ─── 备兑策略核心 ────────────────────────────────────────────────────────────

class CoveredCallStrategy:
    """
    备兑看涨期权策略

    持仓状态:
      - position > 0: 持有标的 + 持有空头Call（备兑）
      - position == 0: 空仓

    调仓规则:
      - 持有标的时，每`roll_days`天卖出新的OTM看涨期权
      - 行权价 = S × (1 + strike_pct)，strike_pct=0.05 表示虚值5%
      - 到期时间默认30天
      - MA信号从buy转sell时，平仓

    Args:
        symbol: 标的代码（如 '510300'）
        strike_pct: 虚值程度，如0.05表示行权价=标的×1.05
        dte: 期权到期天数（默认30）
        roll_days: 换月天数（默认28，接近到期日前平仓）
        r: 无风险利率（默认0.03）
        use_ma_exit: 是否用MA信号作为退出条件（默认True）
        ma_fast: 快线MA周期（默认10）
        ma_slow: 慢线MA周期（默认20）
    """

    def __init__(
        self,
        symbol: str,
        strike_pct: float = 0.05,
        dte: int = 30,
        roll_days: int = 28,
        r: float = 0.03,
        use_ma_exit: bool = True,
        ma_fast: int = 10,
        ma_slow: int = 20,
    ):
        self.symbol = symbol
        self.strike_pct = strike_pct
        self.dte = dte
        self.roll_days = roll_days
        self.r = r
        self.use_ma_exit = use_ma_exit
        self.ma_fast = ma_fast
        self.slow = ma_slow

    def name(self) -> str:
        return (f"CoveredCall({self.symbol}, strike={int(self.strike_pct*100)}%OTM, "
                f"dte={self.dte}, roll={self.roll_days}d)")

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            df: 含 'close' 列的DataFrame，index是date，columns是标的

        Returns:
            DataFrame: 含 'signal' 列（+1=买入持有, 0=空仓）
        """
        S = df['close'].values
        dates = df.index
        n = len(df)

        # 计算MA信号
        ma_fast = pd.Series(S).rolling(self.ma_fast).mean().values
        ma_slow = pd.Series(S).rolling(self.slow).mean().values

        # 波动率（20日）
        vol = np.zeros(n)
        for i in range(self.slow, n):
            rets = np.diff(S[max(0, i-20):i+1]) / S[max(0, i-20):i]
            rets = rets[~np.isnan(rets)]
            if len(rets) >= 10:
                vol[i] = np.std(rets) * np.sqrt(252)

        # 初始化
        signals = np.zeros(n)
        position = 0       # 0=空仓, 1=持仓
        call_pos = 0       # 0=无call空头, 1=持有空头call
        days_since_roll = 999  # 距离上次卖出期权的交易日

        # 期权簿记
        call_strike = 0.0
        call_premium = 0.0
        call_expiry_days = 0

        for i in range(self.slow, n):
            price = S[i]
            if pd.isna(price) or price <= 0:
                signals[i] = 0
                continue

            iv = vol[i] if vol[i] > 0 else 0.20

            # ── 持仓状态 ──────────────────────────────────────────
            if position == 1:
                days_since_roll += 1

                # 检查MA退出信号
                exit_signal = False
                if self.use_ma_exit and not np.isnan(ma_fast[i]) and not np.isnan(ma_slow[i]):
                    if ma_fast[i] < ma_slow[i]:
                        exit_signal = True

                # 期权到期/换月
                roll_signal = (days_since_roll >= self.roll_days)

                # 到期处理：若虚值则归零
                if call_pos == 1:
                    if call_expiry_days <= 0:
                        call_pos = 0
                        call_premium = 0.0
                    else:
                        call_expiry_days -= 1

                if exit_signal or roll_signal:
                    # 平仓标的
                    signals[i] = 0
                    position = 0
                    call_pos = 0
                    days_since_roll = 999
                    call_premium = 0.0
                else:
                    signals[i] = 1  # 继续持有

            # ── 空仓状态 ──────────────────────────────────────────
            else:
                # 检查MA买入信号
                if not np.isnan(ma_fast[i]) and not np.isnan(ma_slow[i]):
                    if ma_fast[i] > ma_slow[i]:
                        signals[i] = 1
                        position = 1
                        days_since_roll = 0

                        # 立即卖出OTM Call
                        strike = price * (1 + self.strike_pct)
                        T = self.dte / 365
                        call_premium = bs_call_price(price, strike, T, self.r, iv)
                        call_strike = strike
                        call_expiry_days = self.dte
                        call_pos = 1
                    else:
                        signals[i] = 0
                else:
                    signals[i] = 0

        result = pd.DataFrame({'signal': signals}, index=dates)
        result.index.name = 'date'
        return result

    def premium_expected(self, price: float, iv: float = 0.20) -> float:
        """
        估算当前卖出OTM Call可获得的权利金（年化）

        Args:
            price: 标的当前价格
            iv: 隐含波动率

        Returns:
            单次权利金（元/股）
        """
        strike = price * (1 + self.strike_pct)
        T = self.dte / 365
        return bs_call_price(price, strike, T, self.r, iv)


# ─── 绩效分析辅助 ─────────────────────────────────────────────────────────────

def analyze_covered_call_vs_hold(
    df: pd.DataFrame,
    symbol: str,
    strike_pct: float = 0.05,
    dte: int = 30,
    roll_days: int = 28,
    initial_capital: float = 100000,
) -> dict:
    """
    对比：Buy&Hold vs Covered Call 策略表现

    Args:
        df: OHLC数据
        symbol: 标的代码
        strike_pct: 虚值程度
        dte: 期权到期天数
        roll_days: 换月天数
        initial_capital: 初始资金

    Returns:
        dict: 含两个策略的绩效指标
    """
    prices = df['close']
    n = len(prices)

    # ── BH基准 ──────────────────────────────────────────────────
    shares_bh = initial_capital / prices.iloc[0]
    bh_values = prices * shares_bh
    bh_returns = bh_values.pct_change().dropna()
    bh_total = bh_values.iloc[-1]
    bh_annual = (bh_total / initial_capital) ** (252 / n) - 1
    bh_max_dd = ((bh_values / bh_values.cummax()) - 1).min()
    bh_sharpe = bh_returns.mean() / bh_returns.std() * np.sqrt(252) if bh_returns.std() > 0 else 0

    # ── Covered Call ───────────────────────────────────────────
    strategy = CoveredCallStrategy(symbol, strike_pct=strike_pct, dte=dte, roll_days=roll_days)
    signals = strategy.generate(df)
    positions = signals['signal'].values

    # 估算波动率
    vol_arr = np.zeros(n)
    for i in range(20, n):
        rets = np.diff(prices.iloc[max(0,i-20):i+1].values)
        if len(rets) >= 5:
            vol_arr[i] = np.std(rets[~np.isnan(rets)]) * np.sqrt(252)

    cc_cash = initial_capital
    cc_shares = 0
    call_premium_acc = 0
    call_strike = 0.0
    call_days_left = 0

    daily_values = []
    peak = initial_capital

    for i in range(len(prices)):
        price = prices.iloc[i]
        signal = positions[i] if i < len(positions) else 0
        iv = vol_arr[i] if vol_arr[i] > 0 else 0.20

        # 期权到期处理
        if call_days_left > 0:
            call_days_left -= 1
            if call_days_left == 0:
                # 到期结算：虚值归零，实值被行权
                if price > call_strike:
                    # 被行权：卖出股票
                    cc_shares = 0

        if signal == 1 and cc_shares == 0:
            # 买入标的
            cc_shares = cc_cash / price
            cc_cash = 0

            # 卖出OTM Call
            strike = price * (1 + strike_pct)
            T = dte / 365
            premium = bs_call_price(price, strike, T, 0.03, iv)
            call_premium_acc += premium
            call_strike = strike
            call_days_left = dte

        elif signal == 0 and cc_shares > 0:
            # 卖出标的
            cc_cash = cc_shares * price
            cc_shares = 0
            call_days_left = 0

        # 每日组合价值
        portfolio_value = cc_cash + cc_shares * price
        daily_values.append(portfolio_value)
        if portfolio_value > peak:
            peak = portfolio_value
        drawdown = (portfolio_value - peak) / peak

    daily_values = np.array(daily_values)
    daily_values = np.maximum(daily_values, 1)  # 防除零
    cc_returns = np.diff(daily_values) / daily_values[:-1]
    cc_returns = cc_returns[~np.isnan(cc_returns)]

    cc_total = daily_values[-1]
    cc_annual = (cc_total / initial_capital) ** (252 / n) - 1
    cc_sharpe = cc_returns.mean() / cc_returns.std() * np.sqrt(252) if cc_returns.std() > 0 else 0
    cc_max_dd = ((daily_values / np.maximum.accumulate(daily_values)) - 1).min()

    return {
        'buy_hold': {
            'final_value': round(bh_total, 2),
            'annual_return': round(bh_annual * 100, 2),
            'sharpe': round(bh_sharpe, 2),
            'max_drawdown': round(bh_max_dd * 100, 2),
            'total_premium': 0,
        },
        'covered_call': {
            'final_value': round(cc_total, 2),
            'annual_return': round(cc_annual * 100, 2),
            'sharpe': round(cc_sharpe, 2),
            'max_drawdown': round(cc_max_dd * 100, 2),
            'total_premium': round(call_premium_acc, 2),
        },
        'params': {
            'symbol': symbol,
            'strike_pct': strike_pct,
            'dte': dte,
            'roll_days': roll_days,
        }
    }


# ─── 参数扫描 ────────────────────────────────────────────────────────────────

def grid_search_covered_call(
    df: pd.DataFrame,
    symbol: str,
    initial_capital: float = 100000,
) -> pd.DataFrame:
    """
    网格搜索最优备兑参数
    """
    results = []
    for strike_pct in [0.02, 0.05, 0.08, 0.10, 0.15]:
        for dte in [7, 14, 30, 45, 60]:
            for roll_days in [dte - 2, dte, dte + 2]:
                if roll_days < 1:
                    continue
                r = analyze_covered_call_vs_hold(
                    df, symbol,
                    strike_pct=strike_pct,
                    dte=dte,
                    roll_days=roll_days,
                    initial_capital=initial_capital,
                )
                cc = r['covered_call']
                bh = r['buy_hold']
                results.append({
                    'strike_pct': strike_pct,
                    'dte': dte,
                    'roll_days': roll_days,
                    'cc_annual': cc['annual_return'],
                    'cc_sharpe': cc['sharpe'],
                    'cc_max_dd': cc['max_drawdown'],
                    'cc_premium': cc['total_premium'],
                    'bh_annual': bh['annual_return'],
                    'excess': cc['annual_return'] - bh['annual_return'],
                })

    df_result = pd.DataFrame(results)
    df_result = df_result.sort_values('cc_sharpe', ascending=False)
    return df_result


if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from data.fetcher import fetch_etf
    from datetime import date

    print("=" * 60)
    print("备兑期权策略（Covered Call）分析")
    print("=" * 60)

    # 加载数据
    os.environ['USE_YAHOO'] = '1'
    df = fetch_etf('510300', '20200101', '20260508')
    if df.empty or len(df) < 60:
        print("数据不足")
        sys.exit(1)

    # fetch_etf返回date列，需要设为索引
    if 'date' in df.columns:
        df = df.set_index('date')
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    first_date = df.index[0]
    last_date = df.index[-1]
    if hasattr(first_date, 'date'):
        first_str = first_date.strftime('%Y-%m-%d')
        last_str = last_date.strftime('%Y-%m-%d')
    else:
        first_str = str(first_date)
        last_str = str(last_date)

    print(f"标的: 沪深300ETF (510300)")
    print(f"数据区间: {first_str} ~ {last_str}")
    print(f"数据量: {len(df)} 个交易日")
    print()

    # ── 参数扫描 ──────────────────────────────────────────────────
    print("⏳ 参数扫描中...")
    grid = grid_search_covered_call(df, '510300')
    print("\nTop-10 参数（按夏普排序）：")
    print(grid.head(10).to_string(index=False))
    print()

    # ── 最优 vs BH ────────────────────────────────────────────────
    best = grid.iloc[0]
    result = analyze_covered_call_vs_hold(
        df, '510300',
        strike_pct=best['strike_pct'],
        dte=int(best['dte']),
        roll_days=int(best['roll_days']),
    )

    bh = result['buy_hold']
    cc = result['covered_call']

    print("=" * 60)
    print(f"最优参数: OTM{int(best['strike_pct']*100)}% | DTE={int(best['dte'])}天 | 换月={int(best['roll_days'])}天")
    print("=" * 60)
    print(f"{'指标':<20} {'BH':>12} {'备兑策略':>12} {'超额':>12}")
    print(f"{'-'*60}")
    print(f"{'最终权益':<20} {bh['final_value']:>12,.0f} {cc['final_value']:>12,.0f} {cc['final_value']-bh['final_value']:>+12,.0f}")
    print(f"{'年化收益':<20} {bh['annual_return']:>11.1f}% {cc['annual_return']:>11.1f}% {cc['annual_return']-bh['annual_return']:>+11.1f}%")
    print(f"{'夏普比率':<20} {bh['sharpe']:>12.2f} {cc['sharpe']:>12.2f} {cc['sharpe']-bh['sharpe']:>+12.2f}")
    print(f"{'最大回撤':<20} {bh['max_drawdown']:>11.1f}% {cc['max_drawdown']:>11.1f}% {cc['max_drawdown']-bh['max_drawdown']:>+11.1f}%")
    print(f"{'累计权利金':<20} {'-':>12} {cc['total_premium']:>12,.0f}")
    print("=" * 60)
