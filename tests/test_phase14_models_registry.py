"""Phase 14.3 + 14.5 — ML 模型包装 + 模型注册表测试"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.model_wrappers import (
    RidgeModel,
    LinearWrapper,
    purged_time_series_split,
    get_available_models,
)
from data_store.db import get_connection
from data_store.model_registry import ModelRegistry


# ===== P14.3 模型包装 =====

def test_linear_wrapper_fit_predict():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(100, 3))
    y = x @ np.array([0.5, -0.3, 0.2]) + rng.normal(0, 0.1, 100)

    m = LinearWrapper()
    m.fit(x, y)
    pred = m.predict(x[:5])
    assert pred.shape == (5,)


def test_ridge_model_fit_predict_with_alpha():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(100, 3))
    y = x @ np.array([0.5, -0.3, 0.2]) + rng.normal(0, 0.1, 100)

    m = RidgeModel(alpha=0.1)
    m.fit(x, y)
    pred = m.predict(x)
    # MSE 应较小
    mse = float(np.mean((pred - y) ** 2))
    assert mse < 0.5


def test_get_available_models_returns_dict():
    avail = get_available_models()
    assert "linear" in avail
    assert "ridge" in avail
    # xgboost/lightgbm 可能 False（未装），但必须列出
    assert "xgboost" in avail
    assert "lightgbm" in avail
    assert isinstance(avail["linear"], bool)


def test_purged_time_series_split_no_leakage():
    n = 100
    indices = np.arange(n)
    splits = list(purged_time_series_split(n, n_splits=3, embargo=5))
    assert len(splits) == 3
    for train_idx, test_idx in splits:
        # train 严格在 test 之前 + embargo gap
        assert train_idx.max() < test_idx.min()
        assert (test_idx.min() - train_idx.max()) >= 5


# ===== P14.5 模型注册表 =====

def test_model_registry_table_created(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        ModelRegistry(conn)  # 触发建表
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('model_registry','factor_ic_history')"
        )
        names = {row[0] for row in cur.fetchall()}
    assert names == {"model_registry", "factor_ic_history"}


def test_model_registry_register_and_query(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        reg = ModelRegistry(conn)
        version = reg.register_model(
            model_name="xgb_v1",
            model_type="xgboost",
            features=["mom_5d", "vol_20d"],
            metrics={"ic": 0.045, "ir": 0.85, "sharpe": 1.2},
            artifact_path="models/xgb_v1.pkl",
            notes="test promote",
        )
        assert version >= 1
        # 同名再注册版本递增
        v2 = reg.register_model(
            model_name="xgb_v1", model_type="xgboost",
            features=["mom_5d", "vol_20d"],
            metrics={"ic": 0.05},
            artifact_path="models/xgb_v1_b.pkl",
        )
        assert v2 == version + 1

        all_versions = reg.list_versions("xgb_v1")
        assert len(all_versions) == 2

        latest = reg.get_latest("xgb_v1")
        assert latest["version"] == v2
        assert latest["status"] == "candidate"


def test_model_registry_promote_to_champion(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        reg = ModelRegistry(conn)
        v1 = reg.register_model("m", "linear", ["f"], {"ic": 0.04}, "p1")
        v2 = reg.register_model("m", "linear", ["f"], {"ic": 0.05}, "p2")

        reg.promote("m", v2)
        champ = reg.get_champion("m")
        assert champ["version"] == v2
        assert champ["status"] == "champion"

        # 之前的 champion 自动降级
        v1_info = reg.get_version("m", v1)
        assert v1_info["status"] == "archived"


def test_factor_ic_history_log(tmp_path):
    with get_connection(str(tmp_path / "q.db")) as conn:
        reg = ModelRegistry(conn)
        reg.log_factor_ic(
            factor_name="mom_20d",
            date="2024-06-30",
            ic_value=0.038,
            sample_size=120,
            method="pearson",
        )
        reg.log_factor_ic(
            factor_name="mom_20d", date="2024-07-31",
            ic_value=0.042, sample_size=125, method="pearson",
        )
        history = reg.fetch_factor_ic("mom_20d")
        assert len(history) == 2
        assert abs(history[-1]["ic_value"] - 0.042) < 1e-9
