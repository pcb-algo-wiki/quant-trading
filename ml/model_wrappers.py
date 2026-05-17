"""Phase 14.3 — ML 模型包装

提供统一 fit/predict 接口，并按 sklearn/xgboost/lightgbm 可用性优雅降级。

约定：
- 所有模型实现 .fit(X, y) -> self 和 .predict(X) -> np.ndarray
- xgboost/lightgbm 不可用时，get_available_models 返回 False
- purged_time_series_split：避免 train 与 test 时间重叠的纯函数 CV 切片器
"""
from __future__ import annotations

import importlib
from typing import Iterator

import numpy as np


# ---------- 内置 LinearWrapper：复用项目原 LinearReturnModel ----------

class LinearWrapper:
    """无外部依赖的 OLS 包装。"""

    def __init__(self):
        self.coef_: np.ndarray | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> "LinearWrapper":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        x1 = np.c_[np.ones(len(x)), x]
        self.coef_ = np.linalg.pinv(x1.T @ x1) @ x1.T @ y
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("model not fitted")
        x = np.asarray(x, dtype=float)
        x1 = np.c_[np.ones(len(x)), x]
        return x1 @ self.coef_


# ---------- RidgeModel：闭式解，无外部依赖 ----------

class RidgeModel:
    """Ridge 回归（L2 正则化），闭式解。

    优先用 sklearn.linear_model.Ridge，否则用 numpy 闭式解。
    """

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.coef_: np.ndarray | None = None
        self._impl = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> "RidgeModel":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        try:
            from sklearn.linear_model import Ridge
            self._impl = Ridge(alpha=self.alpha)
            self._impl.fit(x, y)
            return self
        except ImportError:
            pass
        # numpy 闭式：β = (XᵀX + αI)⁻¹ Xᵀy
        x1 = np.c_[np.ones(len(x)), x]
        n_feat = x1.shape[1]
        reg = self.alpha * np.eye(n_feat)
        reg[0, 0] = 0.0  # 不正则化截距
        self.coef_ = np.linalg.solve(x1.T @ x1 + reg, x1.T @ y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        if self._impl is not None:
            return self._impl.predict(x)
        if self.coef_ is None:
            raise RuntimeError("model not fitted")
        x1 = np.c_[np.ones(len(x)), x]
        return x1 @ self.coef_


# ---------- XGBoost / LightGBM 占位（按可用性优雅降级） ----------

class XGBoostModel:
    """xgboost 包装；若未安装则 fit 抛 RuntimeError。"""

    def __init__(self, **params):
        self.params = {"n_estimators": 200, "max_depth": 5, "learning_rate": 0.05,
                       "objective": "reg:squarederror", **params}
        self._impl = None

    def fit(self, x, y):
        try:
            import xgboost as xgb
        except ImportError as e:
            raise RuntimeError("xgboost not installed; pip install xgboost") from e
        self._impl = xgb.XGBRegressor(**self.params)
        self._impl.fit(np.asarray(x), np.asarray(y))
        return self

    def predict(self, x):
        if self._impl is None:
            raise RuntimeError("model not fitted")
        return self._impl.predict(np.asarray(x))


class LightGBMModel:
    def __init__(self, **params):
        self.params = {"n_estimators": 200, "max_depth": 5, "learning_rate": 0.05, **params}
        self._impl = None

    def fit(self, x, y):
        try:
            import lightgbm as lgb
        except ImportError as e:
            raise RuntimeError("lightgbm not installed; pip install lightgbm") from e
        self._impl = lgb.LGBMRegressor(**self.params)
        self._impl.fit(np.asarray(x), np.asarray(y))
        return self

    def predict(self, x):
        if self._impl is None:
            raise RuntimeError("model not fitted")
        return self._impl.predict(np.asarray(x))


def get_available_models() -> dict[str, bool]:
    """返回支持的模型 + 是否可用。"""
    def _has(mod: str) -> bool:
        try:
            importlib.import_module(mod)
            return True
        except ImportError:
            return False
    return {
        "linear": True,
        "ridge": True,
        "xgboost": _has("xgboost"),
        "lightgbm": _has("lightgbm"),
    }


# ---------- Purged Time-Series CV ----------

def purged_time_series_split(
    n_samples: int,
    n_splits: int = 5,
    embargo: int = 0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Purged + embargo 时序 CV。

    生成 n_splits 个 (train_idx, test_idx) 对：
    - train 区段位于 test 之前
    - train.max() + embargo <= test.min()
    """
    if n_samples <= 0 or n_splits <= 0:
        return
    test_size = n_samples // (n_splits + 1)
    if test_size <= 0:
        return
    for i in range(n_splits):
        test_start = (i + 1) * test_size
        test_end = min(test_start + test_size, n_samples)
        if test_start >= n_samples:
            break
        train_end = max(0, test_start - embargo)
        if train_end <= 0:
            continue
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        if len(train_idx) and len(test_idx):
            yield train_idx, test_idx
