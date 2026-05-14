from __future__ import annotations

import numpy as np


class LinearReturnModel:
    """
    轻量线性回归基线模型（无外部依赖）。
    """

    def __init__(self):
        self.coef_: np.ndarray | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> "LinearReturnModel":
        x1 = np.c_[np.ones(len(x)), x]
        self.coef_ = np.linalg.pinv(x1.T @ x1) @ x1.T @ y
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("model not fitted")
        x1 = np.c_[np.ones(len(x)), x]
        return x1 @ self.coef_
