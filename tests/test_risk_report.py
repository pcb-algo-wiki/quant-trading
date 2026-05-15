import pandas as pd

from research.risk_report import build_risk_report


def test_build_risk_report_contains_var_and_drawdown():
    equity_curve = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="B"),
            "equity": [100000, 101000, 98000, 97000, 99000, 99500],
        }
    )
    exposures = {"ai_compute": 0.32, "semiconductor": 0.18}
    report = build_risk_report(equity_curve=equity_curve, industry_exposure=exposures)
    assert "var_95" in report
    assert report["max_drawdown"] <= 0
