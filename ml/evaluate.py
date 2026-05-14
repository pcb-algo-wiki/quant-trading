from __future__ import annotations

import numpy as np
import pandas as pd


def walk_forward_evaluate(
    model,
    dataset: pd.DataFrame,
    feature_cols: list[str],
    label_col: str = "label",
    train_window: int = 120,
    test_window: int = 20,
) -> dict:
    n = len(dataset)
    mses: list[float] = []
    windows = 0
    for start in range(0, n - train_window - test_window + 1, test_window):
        train = dataset.iloc[start : start + train_window]
        test = dataset.iloc[start + train_window : start + train_window + test_window]
        x_train = train[feature_cols].values
        y_train = train[label_col].values
        x_test = test[feature_cols].values
        y_test = test[label_col].values
        if len(test) == 0:
            continue
        model.fit(x_train, y_train)
        pred = model.predict(x_test)
        mses.append(float(np.mean((pred - y_test) ** 2)))
        windows += 1
    return {"n_windows": windows, "avg_mse": float(np.mean(mses)) if mses else 0.0}
