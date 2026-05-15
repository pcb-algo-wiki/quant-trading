#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import pandas as pd


def run_shadow_session(recommendations: list[dict], market_fills: pd.DataFrame) -> dict:
    rows = []
    for rec in recommendations:
        symbol = rec["symbol"]
        row = market_fills[market_fills["symbol"] == symbol]
        if row.empty:
            continue
        actual = float(row.iloc[0]["fill_price"])
        target = float(rec["target_price"])
        slippage_bp = (actual - target) / target * 10000
        if rec["side"] == "SELL":
            slippage_bp = -slippage_bp
        rows.append(
            {
                "symbol": symbol,
                "side": rec["side"],
                "target_price": target,
                "actual_price": actual,
                "slippage_bp": slippage_bp,
            }
        )

    out = pd.DataFrame(rows)
    avg_slippage_bp = float(out["slippage_bp"].mean()) if not out.empty else 0.0
    return {"n_orders": len(out), "avg_slippage_bp": avg_slippage_bp, "details": rows}


def save_shadow_report(result: dict, path: str = "results/reports/shadow/latest.json") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    demo = run_shadow_session([], pd.DataFrame(columns=["symbol", "fill_price"]))
    save_shadow_report(demo)
    print(demo)
