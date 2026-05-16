# Copilot instructions for `quant-trading`

## Commands

### Install dependencies

```bash
python -m pip install -r requirements.txt
```

### Tests

The repository uses `pytest` under `tests/`, but `requirements.txt` does not currently install `pytest`, so a fresh environment may need it separately.

```bash
python -m pytest
```

Run a single file:

```bash
python -m pytest tests/test_data_store.py
```

Run a single test:

```bash
python -m pytest tests/test_data_store.py::test_news_items_hash_dedup
```

## High-level architecture

### Entry points and execution modes

- `run.py` is the main dispatcher. It still owns the original backtest flows (`--etf`, `--compare`, `--wf`, `--multifactor`, `--rotation`, `--ensemble`), but it also routes newer operational tasks such as `--update-data`, `--update-knowledge`, `--industry-map`, `--train-ml`, `--ml-backtest`, and `--daily-pipeline`.
- Treat this repo as two connected systems: a classic strategy/backtest stack and a newer daily research pipeline built on structured storage, knowledge extraction, and ML evaluation.

### Strategy and backtest stack

- `data/` fetches ETF, stock, macro, and news inputs.
- `strategies/` produces signal frames, typically with `signal` and `position` columns.
- `backtest/engine.py` is the base engine that consumes OHLCV data plus those signal frames and returns an equity curve, metrics, and extracted trades.
- `backtest/risk.py` wraps the same flow with `RiskManager` and `BacktestEngineV2` for stop-loss, trailing stop, drawdown, and position-sizing behavior.

### Daily research pipeline

- `scripts/daily_pipeline.py` is the orchestration layer for the newer workflow. It runs, in order:
  1. `scripts/update_data_store.py`
  2. `scripts/update_knowledge.py`
  3. `scripts/update_events.py`
  4. `scripts/train_ml_strategy.py`
  5. `scripts/run_ml_backtest.py`
- `research/report_builder.py` turns the outputs of those steps into a single summary string.

### Structured data, knowledge, and ML layers

- `data_store/` is a SQLite-backed cache and event store. `data_store.db.get_connection()` always bootstraps schema creation, and the default DB path is `data/cache/quant_data.db`.
- `data_store/repositories.py` is the write/read boundary for persisted data. Market bars and news ingestion are idempotent by design: bars use `(symbol, date, source)` keys, and news uses a content hash for deduplication.
- `knowledge/` converts news rows into `KnowledgeDocument` objects, groups them by taxonomy tag, and emits industry cards.
- `scripts/update_events.py` and `research/` sit beside that layer to turn news into event lists and industry scores.
- `ml/` is intentionally lightweight: features, labels, dataset assembly, a small linear baseline model, walk-forward evaluation, and conversion from predictions back into signal frames for backtests.

### Execution and trading safeguards

- `execution/paper.py` models a stateful paper-trading account with orders, trades, positions, and an equity curve.
- `execution/broker.py` defines the adapter interface plus mock/replay implementations used by tests and consistency checks.
- `execution/live_guard.py` and `execution/risk_controls.py` enforce pre-trade safety constraints separately from the backtest risk engine.

## Key conventions

- Use `utils.config.cfg` as the shared configuration entry point instead of loading `config.yaml` ad hoc. It loads `.env`, resolves `${VAR}` placeholders, and applies supported `QUANT_*` environment overrides.
- Prefer `cfg.enabled_etf_codes` or other config-driven values over hardcoding the tradable universe in new pipeline code.
- Preserve the repo's signal contract: strategy and ML outputs are expected to produce `signal` and `position` columns that downstream backtest code can consume directly.
- Keep ingestion paths idempotent. Existing repositories use `INSERT OR IGNORE`, primary keys, or content hashes to avoid duplicate bars, news, and pipeline records.
- Tests rely heavily on `pytest`, `tmp_path`, and `monkeypatch` to isolate filesystem, database, and pipeline side effects. Follow that pattern for new tests instead of writing against shared local state.
- The project is Chinese-first in README text, comments, and many user-facing strings. Match the surrounding language when editing docs, CLI output, or inline comments.
- This repo includes `.claude/skills/` and a checked-in `CLAUDE.md`. For AI-assisted changes, keep those workflow expectations aligned: check for applicable skills first, use design-before-implementation for feature work, and verify with real commands before claiming completion.
