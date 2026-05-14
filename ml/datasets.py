from __future__ import annotations

import pandas as pd


def make_ml_dataset(features: pd.DataFrame, labels: pd.DataFrame, label_col: str) -> pd.DataFrame:
    merged = features.merge(labels[["date", label_col]], on="date", how="left")
    merged = merged.rename(columns={label_col: "label"})
    return merged.dropna(subset=["ret_1d", "mom_5d", "vol_20d", "label"]).reset_index(drop=True)
