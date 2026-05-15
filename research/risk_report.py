from __future__ import annotations

import numpy as np
import pandas as pd


def build_risk_report(equity_curve: pd.DataFrame, industry_exposure: dict[str, float]) -> dict:
    df = equity_curve.copy().reset_index(drop=True)
    returns = df["equity"].pct_change().dropna()
    if len(returns) == 0:
        var_95 = 0.0
    else:
        var_95 = float(np.quantile(returns, 0.05))

    peak = df["equity"].cummax()
    drawdown = (df["equity"] - peak) / peak
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0

    stress = {
        "10pct_market_drop_impact": round(sum(industry_exposure.values()) * -0.10, 4),
    }
    return {
        "var_95": var_95,
        "max_drawdown": max_drawdown,
        "industry_exposure": industry_exposure,
        "stress": stress,
    }
