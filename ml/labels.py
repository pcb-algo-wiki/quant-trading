from __future__ import annotations

import pandas as pd


def build_forward_return_labels(price_df: pd.DataFrame, horizons: tuple[int, ...] = (5, 10, 20)) -> pd.DataFrame:
    df = price_df[["date", "close"]].copy().reset_index(drop=True)
    for h in horizons:
        df[f"fwd_ret_{h}d"] = df["close"].shift(-h) / df["close"] - 1
    return df
