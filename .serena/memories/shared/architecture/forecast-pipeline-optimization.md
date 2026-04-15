# Forecast Pipeline Optimization Architecture

## Performance Profile (748 India tickers, 10-core Mac)

### Per-ticker breakdown
- Prophet.fit(): ~2.5s (CmdStanPy, releases GIL)
- CV accuracy (32 folds): ~3.2s with parallel=None
- Prophet.predict(): ~0.2s
- Regressor load (cached): ~0.05s
- OHLCV (from batch cache): ~0.002s

### Batch I/O (one-time before parallel loop)
- Batch OHLCV: single DuckDB query, 1.38M rows in ~1s
- Batch forecast_runs: single DuckDB query for freshness check, ~0.5s
- Regressor cache: VIX + index + macro loaded once per scope, 10-min TTL
- Only sentiment remains per-ticker (ticker-specific)

### Bulk Writes (after parallel loop)
- `insert_forecast_runs_batch()`: all run metadata in 1 Iceberg commit
- `insert_forecast_series_batch()`: all forecast series in 1 commit (scoped delete by ticker first)
- Backtest data (horizon_months=0) included when CV actually runs

### Worker Configuration
- `max_workers = max(os.cpu_count() // 2, 2)` — 5 on 10-core
- Prophet CV: `parallel=None` (sequential within each thread)
- No nested process spawning — avoids 50-process contention

### CV Reuse (30-day TTL)
- Weekly runs: skip CV if previous accuracy <30 days old
- Monthly: CV recomputes automatically when cache expires
- `force=True` always recomputes CV
- Accuracy drift: 95% of tickers drift <1% MAPE over 30 days

### Freshness Gate (7-day TTL)
- Pre-loaded from batch DuckDB query into `_fc_run_cache` dict
- Dict lookup instead of per-ticker Iceberg read
- Falls back to `stock_repo.get_latest_forecast_run()` for cache misses

### Key files
- `backend/jobs/executor.py`: execute_run_forecasts, _ohlcv_from_cached, batch logic
- `backend/tools/_forecast_shared.py`: _MARKET_CACHE, _MACRO_CACHE, batch DuckDB loads
- `backend/tools/_forecast_accuracy.py`: CV with parallel=None
- `stocks/repository.py`: insert_forecast_runs_batch, insert_forecast_series_batch

### Runtime Results
| Scenario | Time |
|----------|------|
| Monthly force (full CV) | ~34 min |
| Weekly (CV reused) | ~8 min |
| All fresh (skip path) | ~2.2 sec |
