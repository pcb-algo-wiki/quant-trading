#!/usr/bin/env python3
from __future__ import annotations

from data.fetcher import fetch_etf
from ml.features import build_feature_frame
from ml.labels import build_forward_return_labels
from ml.datasets import make_ml_dataset
from ml.models import LinearReturnModel
from ml.signals import predictions_to_signals
from strategies.multi_factor import quick_backtest


def run(symbol: str = "510300", start: str = "20200101", end: str = "20241231") -> dict:
    px = fetch_etf(symbol, start, end).reset_index(drop=True)
    feat = build_feature_frame(px)
    lab = build_forward_return_labels(px, horizons=(5,))
    ds = make_ml_dataset(feat, lab, label_col="fwd_ret_5d")
    feature_cols = ["ret_1d", "mom_5d", "vol_20d"]
    model = LinearReturnModel().fit(ds[feature_cols].values, ds["label"].values)
    ds["pred"] = model.predict(ds[feature_cols].values)
    sig = predictions_to_signals(ds[["date", "close", "pred"]], pred_col="pred")
    return quick_backtest(ds[["date", "close"]], sig[["date", "position", "signal"]])


if __name__ == "__main__":
    print(run())
