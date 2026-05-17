"""Phase 14.1 — 内置因子集"""
from __future__ import annotations

import pandas as pd

from ml.factors.base import BaseFactor, FactorRegistry


class Momentum5D(BaseFactor):
    name = "mom_5d"
    category = "momentum"
    def compute(self, df): return df["close"].pct_change(5)


class Momentum20D(BaseFactor):
    name = "mom_20d"
    category = "momentum"
    def compute(self, df): return df["close"].pct_change(20)


class Momentum60D(BaseFactor):
    name = "mom_60d"
    category = "momentum"
    def compute(self, df): return df["close"].pct_change(60)


class MAGap20D(BaseFactor):
    name = "ma_gap_20d"
    category = "momentum"
    def compute(self, df):
        ma = df["close"].rolling(20).mean()
        return (df["close"] - ma) / ma


class Reversal1D(BaseFactor):
    name = "rev_1d"
    category = "reversal"
    def compute(self, df): return -df["close"].pct_change(1)


class Reversal5D(BaseFactor):
    name = "rev_5d"
    category = "reversal"
    def compute(self, df): return -df["close"].pct_change(5)


class Volatility5D(BaseFactor):
    name = "vol_5d"
    category = "volatility"
    def compute(self, df): return df["close"].pct_change().rolling(5).std()


class Volatility20D(BaseFactor):
    name = "vol_20d"
    category = "volatility"
    def compute(self, df): return df["close"].pct_change().rolling(20).std()


class ATR14(BaseFactor):
    name = "atr_14"
    category = "volatility"
    def compute(self, df):
        h_l = df["high"] - df["low"]
        h_pc = (df["high"] - df["close"].shift(1)).abs()
        l_pc = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        return tr.rolling(14).mean()


class Turnover5D(BaseFactor):
    name = "turnover_5d"
    category = "volume"
    def compute(self, df):
        return df["volume"].rolling(5).mean() / df["volume"].rolling(20).mean()


class VolumeZScore20D(BaseFactor):
    name = "volume_zscore_20d"
    category = "volume"
    def compute(self, df):
        vol = df["volume"]
        mean = vol.rolling(20).mean()
        std = vol.rolling(20).std().replace(0, pd.NA)
        return (vol - mean) / std


class AmountRatio5D(BaseFactor):
    name = "amount_ratio_5d"
    category = "volume"
    def compute(self, df):
        amount = df["close"] * df["volume"]
        return amount.rolling(5).sum() / amount.rolling(20).sum()


class PriceVolumeCorrelation20D(BaseFactor):
    name = "pv_corr_20d"
    category = "volume"
    def compute(self, df):
        return df["close"].rolling(20).corr(df["volume"])


def register_default_factors(reg: FactorRegistry) -> None:
    for cls in (
        Momentum5D, Momentum20D, Momentum60D, MAGap20D,
        Reversal1D, Reversal5D,
        Volatility5D, Volatility20D, ATR14,
        Turnover5D, VolumeZScore20D, AmountRatio5D, PriceVolumeCorrelation20D,
    ):
        reg.register(cls())
