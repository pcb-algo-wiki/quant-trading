from ml.features import build_feature_frame
from ml.labels import build_forward_return_labels
from ml.datasets import make_ml_dataset
from ml.models import LinearReturnModel
from ml.evaluate import walk_forward_evaluate


def test_walk_forward_evaluate_runs(sample_ohlcv):
    feat = build_feature_frame(sample_ohlcv)
    lab = build_forward_return_labels(sample_ohlcv, horizons=(5,))
    ds = make_ml_dataset(feat, lab, label_col="fwd_ret_5d")

    model = LinearReturnModel()
    result = walk_forward_evaluate(model=model, dataset=ds, feature_cols=["ret_1d", "mom_5d", "vol_20d"], label_col="label", train_window=40, test_window=10)
    assert result["n_windows"] >= 1
    assert "avg_mse" in result
