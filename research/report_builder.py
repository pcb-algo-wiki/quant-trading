from __future__ import annotations


def build_daily_summary(payload: dict) -> str:
    data = payload.get("data", {})
    events = payload.get("events", {})
    ml_train = payload.get("ml_train", {})
    ml_backtest = payload.get("ml_backtest", {})
    return (
        f"Data bars={data.get('bars_inserted', 0)}, news={data.get('news_inserted', 0)} | "
        f"Events={events.get('event_count', 0)} | "
        f"ML windows={ml_train.get('n_windows', 0)} mse={ml_train.get('avg_mse', 0)} | "
        f"Backtest return={ml_backtest.get('total_return', 0)}"
    )
