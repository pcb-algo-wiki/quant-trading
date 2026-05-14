from __future__ import annotations

import pandas as pd


def predictions_to_signals(
    df: pd.DataFrame,
    pred_col: str = "pred",
    buy_threshold: float = 0.01,
    sell_threshold: float = -0.01,
) -> pd.DataFrame:
    out = df.copy()
    out["position"] = 0.0
    out.loc[out[pred_col] >= buy_threshold, "position"] = 1.0
    out.loc[out[pred_col] <= sell_threshold, "position"] = 0.0
    out["signal"] = out["position"].diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return out
