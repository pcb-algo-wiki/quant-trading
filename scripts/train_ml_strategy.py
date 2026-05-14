#!/usr/bin/env python3
from __future__ import annotations

from data.fetcher import fetch_etf
from ml.features import build_feature_frame
from ml.labels import build_forward_return_labels
from ml.datasets import make_ml_dataset
from ml.models import LinearReturnModel
from ml.evaluate import walk_forward_evaluate


def run(symbol: str = "510300", start: str = "20200101", end: str = "20241231") -> dict:
    px = fetch_etf(symbol, start, end)
    feat = build_feature_frame(px)
    lab = build_forward_return_labels(px, horizons=(5,))
    ds = make_ml_dataset(feat, lab, label_col="fwd_ret_5d")
    model = LinearReturnModel()
    result = walk_forward_evaluate(
        model=model,
        dataset=ds,
        feature_cols=["ret_1d", "mom_5d", "vol_20d"],
        label_col="label",
        train_window=120,
        test_window=20,
    )
    return {"symbol": symbol, **result}


if __name__ == "__main__":
    print(run())
