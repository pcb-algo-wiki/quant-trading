from __future__ import annotations

import pandas as pd


def build_feature_frame(price_df: pd.DataFrame) -> pd.DataFrame:
    df = price_df.copy().reset_index(drop=True)
    close = df["close"]
    df["ret_1d"] = close.pct_change(1)
    df["mom_5d"] = close.pct_change(5)
    df["vol_20d"] = close.pct_change().rolling(20).std()
    return df
