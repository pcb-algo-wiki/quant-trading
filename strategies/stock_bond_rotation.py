"""
股债轮动策略
===============
基于美林时钟原理的跨资产配置策略

核心逻辑：
  - 经济增长(PMI/pPI)上行 + 通胀下行 → 复苏 → 股票
  - 经济增长上行 + 通胀上行 → 过热 → 商品/股票
  - 经济增长下行 + 通胀上行 → 滞胀 → 国债/现金
  - 经济增长下行 + 通胀下行 → 衰退 → 国债

简化实现（无PMI数据时）：
  使用股债利差(Equity Bond Spread)作为核心信号
  - 利差扩大（股票盈利收益率相对国债上升）→ 股票相对便宜 → 加仓股票
  - 利差收窄 → 减仓股票，加仓国债

ETF标的：
  股票: 510300(沪深300), 510500(中证500), 159915(创业板)
  国债: 511010(国债ETF) 或用 TNX (10年国债收益率)
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, Tuple


def load_tnx() -> pd.Series:
    """加载10年国债收益率"""
    from pathlib import Path
    cache = Path(__file__).parent.parent / "data" / "cache" / "yahoo_TNX.pkl"
    if not cache.exists():
        return pd.Series(dtype=float)
    df = pd.read_pickle(cache)
    if "date" not in df.columns:
        return pd.Series(dtype=float)
    dates = pd.to_datetime(df["date"]).dt.date
    return pd.Series(df["close"].values, index=pd.to_datetime(dates))


def compute_spread_signal(
    equity_price: pd.DataFrame,
    bond_yield: pd.Series,
    pe_base: float = 12.0,
) -> pd.DataFrame:
    """
    计算股债利差信号

    Args:
        equity_price: ETF价格DataFrame (date, close)
        bond_yield: 国债收益率 Series，index=date
        pe_base: 基准PE

    Returns:
        DataFrame with spread, spread_zscore, position
    """
    close = equity_price["close"]

    if "date" in equity_price.columns:
        dates = pd.to_datetime(equity_price["date"])
    else:
        dates = pd.to_datetime(equity_price.index)

    # 估算盈利收益率 E/P（返回小数，如0.083表示8.3%）
    base_price = close.iloc[0]
    pe_estimate = pe_base * (close / base_price)
    ep_series = 1.0 / (pe_estimate + 1e-10)  # E/P，范围0.05~0.15

    # bond_yield是百分比形式（如3.8表示3.8%），转为小数（0.038）
    bond_yield_decimal = bond_yield / 100.0

    # 找共同日期（都用Timestamp比较）
    bond_dates_ts = pd.to_datetime(bond_yield.index)
    dates_ts = dates
    common = set(dates_ts) & set(bond_dates_ts)
    if len(common) == 0:
        return pd.DataFrame({
            "position": [0], "date": [dates[0]], "spread_zscore": [0],
            "close": [0], "bond_yield": [0], "equity_yield": [0]
        })

    # 对齐：用Timestamp
    spread_vals = []
    date_vals = []  # Timestamp
    close_vals = []
    by_vals = []

    dates_list = dates_ts.tolist()
    for i, d in enumerate(dates_list):
        if d in common:
            # 找对应的国债收益率
            bond_idx = bond_yield.index[bond_yield.index == d]
            if len(bond_idx) == 0:
                continue
            by = bond_yield_decimal.iloc[bond_yield.index.get_loc(bond_idx[0])]
            ep = ep_series.iloc[i]
            spread_vals.append(ep - by)  # 利差（单位一致：小数）
            date_vals.append(d)
            close_vals.append(close.values[i])
            by_vals.append(by * 100)  # 存回百分比形式

    if not spread_vals:
        return pd.DataFrame({
            "position": [0], "date": [dates[0]], "spread_zscore": [0],
            "close": [0], "bond_yield": [0], "equity_yield": [0]
        })

    spread = pd.Series(spread_vals, index=date_vals)
    close_aligned = pd.Series(close_vals, index=date_vals)

    # 利差Z-score
    spread_ma = spread.rolling(20).mean()
    spread_std = spread.rolling(20).std()
    zscore = (spread - spread_ma) / (spread_std + 1e-10)

    # 仓位规则（简化版）
    position = pd.Series(0.5, index=spread.index)
    position[zscore > 0.5] = 1.0
    position[zscore > 1.0] = 1.0
    position[zscore < -0.5] = 0.0
    position[zscore < -1.0] = 0.0

    result = pd.DataFrame({
        "date": date_vals,
        "close": close_vals,
        "bond_yield": by_vals,
        # 盈利收益率（E/P）：基准PE=12时约为8.3%，转为小数形式以便与国债收益率比较
        "equity_yield": [e * 100 for e in ep_series[:len(date_vals)]],
        "spread": spread_vals,
        "spread_zscore": zscore.values,
        "position": position.values,
    })

    return result


class StockBondRotationStrategy:
    """
    股债轮动策略

    模式1（纯利差）：基于股债利差Z-score
    模式2（趋势+利差）：趋势确认 + 利差验证
    模式3（风险平价）：股债50/50动态调整

    Args:
        mode: 'spread' | 'trend_spread' | 'risk_parity'
        stock_etf: 股票ETF代码
        bond_etf: 国债ETF代码（可选，传入则用ETF价格计算利差）
        tnx_period: 用TNX作为国债收益率的周期（默认10年）
    """

    def __init__(
        self,
        mode: str = "trend_spread",
        rebalance_days: int = 10,
    ):
        self.mode = mode
        self.rebalance_days = rebalance_days

    def generate(
        self,
        stock_data: pd.DataFrame,
        bond_data: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            stock_data: 股票ETF价格数据 (date, close)
            bond_data: 债券ETF价格数据或国债收益率
        """
        # 加载国债收益率
        if bond_data is not None and isinstance(bond_data, pd.Series):
            bond_yield = bond_data
        else:
            bond_yield = load_tnx()

        # 计算利差信号
        spread_df = compute_spread_signal(stock_data, bond_yield)
        if spread_df.empty:
            return pd.DataFrame({
                "date": stock_data["date"].values if "date" in stock_data.columns else stock_data.index,
                "close": stock_data["close"].values,
                "position": [0] * len(stock_data),
                "signal": [0] * len(stock_data),
            })

        close = stock_data["close"]
        if "date" in stock_data.columns:
            stock_dates = pd.to_datetime(stock_data["date"]).values
        else:
            stock_dates = pd.to_datetime(stock_data.index).values

        # 用spread_df的日期作为基准（国债和股票日期对齐的部分）
        spread_dates = pd.to_datetime(spread_df["date"]).values
        spread_positions = spread_df["position"].values

        # 趋势信号
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        trend = (ma20 > ma60).astype(float).values

        # 模式选择：用spread_df的长度作为position长度
        n_spread = len(spread_df)
        if self.mode == "spread":
            position = spread_positions
        elif self.mode == "trend_spread":
            zscore = spread_df["spread_zscore"].values
            pos = pd.Series(0.5, index=range(len(zscore)))
            pos[zscore > 0] = 1.0
            pos[zscore < -0.5] = 0.0
            # 趋势过滤
            for i in range(len(pos)):
                if trend[i] == 0 and pos.iloc[i] > 0.5:
                    pos.iloc[i] = 0.5
            position = pos.values
        elif self.mode == "risk_parity":
            # 风险平价：股票仓位 = 债券波动率/(股债波动率之和)
            stock_vol = close.pct_change().rolling(20).std()
            # 假设国债波动率为股票的1/3
            bond_vol_est = stock_vol / 3
            total_vol = stock_vol + bond_vol_est + 1e-10
            stock_weight = bond_vol_est / total_vol
            position = stock_weight.clip(0, 1).values
        else:
            position = [0.5] * len(stock_data)

        # 信号
        position_series = pd.Series(position)
        signal = position_series.diff().fillna(0)
        signal = signal.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        # 用spread_df的日期作为基准
        result = pd.DataFrame({
            "date": spread_df["date"].values,
            "close": spread_df["close"].values,
            "position": position,
            "signal": signal.values,
        })

        # 加入利差信息
        if not spread_df.empty:
            result["spread_zscore"] = spread_df["spread_zscore"].values
            result["bond_yield"] = spread_df["bond_yield"].values
            result["equity_yield"] = spread_df["equity_yield"].values

        return result.reset_index(drop=True)


class DualAssetPortfolio:
    """
    股债双资产组合

    同时持有股票ETF和国债ETF，定期再平衡

    Args:
        stock_symbol: 股票ETF代码
        bond_symbol: 国债ETF代码（如511010）
        initial_capital: 初始资金
    """

    def __init__(
        self,
        stock_symbol: str = "510300",
        bond_symbol: str = "511010",
        initial_capital: float = 100_000,
    ):
        self.stock_symbol = stock_symbol
        self.bond_symbol = bond_symbol
        self.initial_capital = initial_capital

    def backtest(
        self,
        stock_data: pd.DataFrame,
        bond_data: pd.DataFrame,
        strategy: Optional[StockBondRotationStrategy] = None,
        commission: float = 0.0003,
        slippage: float = 0.0001,
    ) -> dict:
        """
        运行双资产回测

        Args:
            stock_data: 股票ETF数据 (date, close)
            bond_data: 国债ETF数据 (date, close)
            strategy: 可选轮动策略，传入则使用轮动仓位
        """
        # 对齐日期
        common = set(stock_data["date"]) & set(bond_data["date"])
        if len(common) == 0:
            return {"error": "No common dates"}

        stock = stock_data[stock_data["date"].isin(common)].sort_values("date").reset_index(drop=True)
        bond = bond_data[bond_data["date"].isin(common)].sort_values("date").reset_index(drop=True)

        n = len(stock)
        if n < 60:
            return {"error": "Insufficient data"}

        # 初始仓位
        stock_pos = 0.6  # 默认股6债4
        bond_pos = 0.4

        # 如果有策略，用策略信号
        if strategy is not None:
            signals = strategy.generate(stock_data)
            # 取策略的股票仓位
            if "position" in signals.columns:
                aligned_pos = []
                for d in stock["date"]:
                    rows = signals[signals["date"] == d]
                    if len(rows) > 0:
                        aligned_pos.append(rows["position"].values[0])
                    else:
                        aligned_pos.append(0.5)
                stock_pos_arr = aligned_pos
            else:
                stock_pos_arr = [0.6] * n
        else:
            stock_pos_arr = [0.6] * n

        equity = self.initial_capital
        equity_curve = []
        position = 0
        entry_price = 0

        for i in range(n):
            close_s = stock.at[i, "close"]
            close_b = bond.at[i, "close"]
            date = stock.at[i, "date"]
            target_stock_pos = stock_pos_arr[i] if i < len(stock_pos_arr) else 0.6

            # 再平衡
            if i > 0 and i % strategy.rebalance_days == 0:
                # 按目标仓位调整
                target_stock_pos = stock_pos_arr[i]

            # 计算总权益
            if position > 0:
                stock_value = equity * target_stock_pos
                bond_value = equity * (1 - target_stock_pos)
            else:
                stock_value = equity * target_stock_pos
                bond_value = equity * (1 - target_stock_pos)

            equity_curve.append({
                "date": date,
                "equity": equity,
                "stock_pos": target_stock_pos,
                "bond_pos": 1 - target_stock_pos,
                "close_stock": close_s,
                "close_bond": close_b,
            })

        eq_df = pd.DataFrame(equity_curve)
        stock_bh = (stock["close"].iloc[-1] / stock["close"].iloc[0] - 1) * 100
        bond_bh = (bond["close"].iloc[-1] / bond["close"].iloc[0] - 1) * 100

        return {
            "equity_curve": eq_df,
            "stock_benchmark": stock_bh,
            "bond_benchmark": bond_bh,
            "final_equity": equity,
            "strategy": self.stock_symbol + "/" + self.bond_symbol,
        }
