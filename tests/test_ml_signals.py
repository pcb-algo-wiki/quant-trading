import pandas as pd

from ml.signals import predictions_to_signals


def test_predictions_to_signals_generates_position_and_signal():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="B"),
            "close": [1, 1.1, 1.2, 1.1, 1.3],
            "pred": [-0.01, 0.02, 0.03, -0.02, 0.01],
        }
    )
    out = predictions_to_signals(df, pred_col="pred", buy_threshold=0.01, sell_threshold=-0.01)
    assert {"position", "signal"}.issubset(out.columns)
    assert out["position"].isin([0.0, 1.0]).all()
