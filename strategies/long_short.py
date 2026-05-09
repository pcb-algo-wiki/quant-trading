"""
Long-Short Equity Strategy
- 做多动量最强股票，做空动量最弱股票
- 通过做空指数ETF对冲系统性风险（Beta Neutral）
- 每双周再平衡
"""

import pandas as pd
import numpy as np
from typing import Optional
from strategies.base import Strategy


class LongShortStrategy(Strategy):
    """不使用generate，自定义backtest和calculate_positions"""

    def generate(self, data: pd.DataFrame) -> pd.DataFrame:
        """实现抽象基类，生成动量排名信号"""
        signals = self.generate_signals(data)
        result = pd.DataFrame({"signal": signals})
        result["position"] = result["signal"].clip(lower=0)
        return result

    def __init__(
        self,
        name: str = "LongShort",
        lookback: int = 20,
        top_pct: float = 0.2,
        bottom_pct: float = 0.2,
        hedge_ratio: float = 0.5,
        index_etf: str = "510300",
        min_stocks: int = 10,
    ):
        """
        Parameters
        ----------
        lookback : int
            动量计算回看天数（默认20日）
        top_pct : float
            做多比例前多少（默认0.2 = 前20%做多）
        bottom_pct : float
            做空比例后多少（默认0.2 = 后20%做空）
        hedge_ratio : float
            保证金对冲比例（0~1，0.5=一半仓位用指数空单对冲）
        index_etf : str
            对冲用指数ETF代码（默认510300沪深300）
        min_stocks : int
            最少股票数量（低于此不開倉）
        """
        super().__init__(name)
        self.lookback = lookback
        self.top_pct = top_pct
        self.bottom_pct = bottom_pct
        self.hedge_ratio = hedge_ratio
        self.index_etf = index_etf
        self.min_stocks = min_stocks
        self._portfolio = {}
        self._last_rebalance_date = None
        self._positions = {}

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        data: Multi-index DataFrame, index=(date, code), columns=[open,high,low,close,volume]
        Returns: Series with codes as index, values = signal (+1 long / -1 short / 0 flat)
        """
        if len(data) == 0:
            return pd.Series(dtype=float)

        latest_date = data.index.get_level_values("date").max()
        cutoff = pd.Timestamp(latest_date) - pd.Timedelta(days=self.lookback * 3)

        recent = data[data.index.get_level_values("date") >= cutoff].copy()
        if len(recent) < 30:
            return pd.Series(dtype=float)

        close = recent["close"].unstack()
        returns = close.pct_change(self.lookback).iloc[-1]

        valid = returns.dropna()
        if len(valid) < self.min_stocks:
            return pd.Series(dtype=float)

        long_threshold = valid.quantile(1 - self.top_pct)
        short_threshold = valid.quantile(self.bottom_pct)

        signals = pd.Series(0, index=valid.index)
        signals[valid >= long_threshold] = 1
        signals[valid <= short_threshold] = -1

        return signals

    def rank_signals(self, data: pd.DataFrame, top_n: int = 20) -> pd.Series:
        """
        返回动量排名（仅做多版本），用于精选Top-N
        """
        if len(data) == 0:
            return pd.Series(dtype=float)

        latest_date = data.index.get_level_values("date").max()
        cutoff = pd.Timestamp(latest_date) - pd.Timedelta(days=self.lookback * 3)

        recent = data[data.index.get_level_values("date") >= cutoff].copy()
        if len(recent) < 30:
            return pd.Series(dtype=float)

        close = recent["close"].unstack()
        returns = close.pct_change(self.lookback).iloc[-1]
        valid = returns.dropna()

        rank = valid.rank(ascending=True, pct=True)
        return rank

    def compute_beta(self, stock_returns: pd.Series, index_returns: pd.Series, window: int = 60) -> float:
        """计算个股beta（60日滚动）"""
        aligned = pd.concat([stock_returns, index_returns], axis=1).dropna()
        if len(aligned) < 20:
            return 1.0
        cov = aligned.iloc[-window:].cov().iloc[0, 1]
        var = aligned.iloc[-window:][index_returns.name].var()
        if var == 0:
            return 1.0
        beta = cov / var
        return float(np.clip(beta, 0.3, 2.0))

    def calculate_positions(
        self,
        signals: pd.Series,
        prices: pd.Series,
        capital: float,
        index_price: float,
        index_returns: Optional[pd.Series] = None,
    ) -> dict:
        """
        根据信号计算仓位权重（Beta Neutral）
        signals: {code: +1/-1/0}
        prices: {code: price}
        capital: 总资金
        index_price: 对冲ETF当前价格
        index_returns: 对冲ETF收益率序列（用于计算beta）
        """
        long_codes = signals[signals == 1].index.tolist()
        short_codes = signals[signals == -1].index.tolist()

        if len(long_codes) == 0 and len(short_codes) == 0:
            return {}

        n_long = max(1, len(long_codes))
        n_short = max(1, len(short_codes))

        long_weight_per_stock = (0.5 * capital) / n_long
        short_weight_per_stock = (0.5 * capital) / n_short

        positions = {}

        for code in long_codes:
            p = prices.get(code)
            try:
                pf = float(p)
                if pf == pf and pf > 0:  # NaN check: NaN != NaN
                    shares = int(long_weight_per_stock / pf)
                    if shares > 0:
                        positions[code] = {"shares": shares, "side": "long"}
            except (TypeError, ValueError):
                continue

        for code in short_codes:
            p = prices.get(code)
            try:
                pf = float(p)
                if pf == pf and pf > 0:
                    shares = int(short_weight_per_stock / pf)
                    if shares > 0:
                        positions[code] = {"shares": shares, "side": "short"}
            except (TypeError, ValueError):
                continue

        # 指数对冲仓位
        if index_price > 0 and self.hedge_ratio > 0:
            total_long_value = sum(
                positions[c]["shares"] * prices.get(c, 0)
                for c in long_codes if c in positions
            )
            total_short_value = sum(
                positions[c]["shares"] * prices.get(c, 0)
                for c in short_codes if c in positions
            )

            net_exposure = total_long_value - total_short_value
            hedge_value = abs(net_exposure) * self.hedge_ratio
            index_shares = int(hedge_value / index_price)

            if index_shares > 0:
                net_dir = 1 if net_exposure > 0 else -1
                positions[self.index_etf] = {
                    "shares": index_shares * (-net_dir),
                    "side": "short" if net_dir > 0 else "long"
                }

        return positions

    def backtest(
        self,
        data: pd.DataFrame,
        initial_capital: float = 100000.0,
        rebalance_days: int = 14,
        top_n: int = 20,
        short_n: int = 10,
    ) -> pd.DataFrame:
        """
        完整回测，返回每日权益曲线
        data: Multi-index DataFrame, index=(date, code), columns=[open,high,low,close,volume]
        """
        dates = sorted(data.index.get_level_values("date").unique())
        if len(dates) < 60:
            return pd.DataFrame()

        close = data["close"].unstack()
        close = close.sort_index()

        # Warmup: 跳过数据不足的早期（需要至少min_stocks只股票）
        warmup_end = None
        for d in dates:
            day_count = len(data.loc[d]) if d in data.index else 0
            if day_count >= self.min_stocks:
                warmup_end = d
                break

        if warmup_end is None:
            return pd.DataFrame()

        # 从有足够数据的那天开始
        start_idx = dates.index(warmup_end)
        dates = dates[start_idx:]

        rebalance_date = None
        signals = pd.Series(dtype=float)
        positions = {}

        equity_curve = []
        capital = initial_capital

        for i, date in enumerate(dates):
            if date not in close.index:
                continue

            if rebalance_date is None or (date - rebalance_date).days >= rebalance_days:
                window_end = date
                window_start = date - pd.Timedelta(days=self.lookback * 3)
                window_data = data[
                    (data.index.get_level_values("date") >= window_start) &
                    (data.index.get_level_values("date") <= window_end)
                ]

                if len(window_data) < 30:
                    continue

                rank = self.rank_signals(window_data)
                if len(rank) == 0:
                    continue

                long_codes = rank.nlargest(top_n).index.tolist()
                short_codes = rank.nsmallest(short_n).index.tolist()

                signals = pd.Series(0, index=rank.index)
                signals[long_codes] = 1
                signals[short_codes] = -1

                active_codes = [c for c in signals[signals != 0].index if c in close.columns]
                if len(active_codes) < 5:
                    continue

                prices = {}
                for c in active_codes:
                    p = close.loc[date, c]
                    if not pd.isna(p) and p > 0:
                        prices[c] = float(p)
                positions = self.calculate_positions(
                    signals, prices, capital,
                    close.loc[date, self.index_etf] if self.index_etf in close.columns and not pd.isna(close.loc[date, self.index_etf]) else 100
                )

                rebalance_date = date

            if i == 0:
                equity = initial_capital
            else:
                prev_date = dates[i - 1]
                if prev_date not in close.index:
                    equity = capital
                else:
                    if len(positions) == 0:
                        equity = capital
                    else:
                        prev_prices = {}
                        for c in positions:
                            if c in close.columns:
                                p = close.loc[prev_date, c]
                                try:
                                    pf = float(p)
                                    if pf == pf and pf > 0:
                                        prev_prices[c] = pf
                                except (TypeError, ValueError):
                                    continue
                        pnl = 0
                        for code, pos in positions.items():
                            if code not in prev_prices:
                                continue
                            cp = close.loc[date, code]
                            try:
                                cpf = float(cp)
                                if cpf != cpf:  # NaN
                                    continue
                            except (TypeError, ValueError):
                                continue
                            price_change = cpf - prev_prices[code]
                            value = pos["shares"] * prev_prices[code]
                            if pos["side"] == "short":
                                pnl -= pos["shares"] * price_change
                            else:
                                pnl += pos["shares"] * price_change
                        equity = capital + pnl

            capital = equity
            equity_curve.append({"date": date, "equity": equity})

        df = pd.DataFrame(equity_curve)
        if len(df) > 0:
            df["returns"] = df["equity"].pct_change().fillna(0)
            df["benchmark"] = (1 + df["returns"]).cumprod().apply(lambda x: x - 1)
        return df

    def __repr__(self):
        return (
            f"LongShort(lookback={self.lookback}, top_pct={self.top_pct}, "
            f"bottom_pct={self.bottom_pct}, hedge={self.hedge_ratio}, "
            f"index={self.index_etf})"
        )
