# Architecture Overview

## Current modules

1. **data/**: market/news/fundamental data fetching and cache.
2. **strategies/**: signal generation (trend, rotation, multi-factor).
3. **backtest/**: backtest engine and risk controls.
4. **execution/**: paper trading execution and order lifecycle.
5. **scripts/**: daily report, dashboard, strategy runners.
6. **utils/**: config, retry, notification helpers.

## Data flow

1. Fetch market/news/fundamental data from providers (`data/*`).
2. Clean/validate input data (`data/quality.py`).
3. Build strategy signals (`strategies/*`).
4. Evaluate via backtest (`backtest/*`) or paper account (`execution/*`).
5. Publish artifacts via dashboard and daily report (`scripts/*`).

## Phase-0 boundaries

This phase keeps existing behavior and introduces explicit extension boundaries:

- **data_store/**: persistent storage and repositories for structured datasets.
- **knowledge/**: industry taxonomy, source docs, and knowledge cards.
- **research/**: event extraction, industry scoring, leaderboards/reports.
- **ml/**: feature/label dataset, model training and evaluation.

These modules are introduced as package boundaries first, then implemented in next phases.
