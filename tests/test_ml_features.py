import pandas as pd

from ml.features import build_feature_frame
from ml.labels import build_forward_return_labels
from ml.datasets import make_ml_dataset


def test_build_feature_frame_basic_columns(sample_ohlcv):
    df = build_feature_frame(sample_ohlcv)
    assert {"ret_1d", "mom_5d", "vol_20d"}.issubset(df.columns)


def test_make_ml_dataset_joins_features_and_labels(sample_ohlcv):
    features = build_feature_frame(sample_ohlcv)
    labels = build_forward_return_labels(sample_ohlcv, horizons=(5,))
    ds = make_ml_dataset(features, labels, label_col="fwd_ret_5d")
    assert "label" in ds.columns
    assert len(ds) > 0
