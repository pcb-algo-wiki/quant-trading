from scripts.daily_pipeline import run_daily_pipeline


def test_run_daily_pipeline_combines_step_results(monkeypatch):
    monkeypatch.setattr("scripts.daily_pipeline.update_data_store_run", lambda: {"bars_inserted": 10, "news_inserted": 5})
    monkeypatch.setattr("scripts.daily_pipeline.update_knowledge_run", lambda: {"ai_compute": {"doc_count": 3}})
    monkeypatch.setattr("scripts.daily_pipeline.update_events_run", lambda: {"event_count": 8, "industry_count": 2})
    monkeypatch.setattr("scripts.daily_pipeline.train_ml_run", lambda: {"n_windows": 4, "avg_mse": 0.01})
    monkeypatch.setattr("scripts.daily_pipeline.run_ml_backtest_run", lambda: {"total_return": 5.2})

    result = run_daily_pipeline()
    assert result["data"]["bars_inserted"] == 10
    assert result["events"]["event_count"] == 8
    assert "ml_train" in result and "ml_backtest" in result
