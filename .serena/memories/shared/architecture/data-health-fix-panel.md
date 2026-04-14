# Data Health Fix Panel (Maintenance Page)

## Overview
The Data Health panel on Admin > Maintenance shows 5 cards (OHLCV, Analytics, Sentiment, Piotroski, Forecasts) with fix buttons that trigger the same pipeline executors as the scheduler.

## API Endpoints
- `POST /admin/data-health/fix` — triggers async fix, returns `{run_id, status}`
  - Body: `{target: "ohlcv"|"analytics"|"sentiment"|"piotroski"|"forecasts", mode: "stale_only"|"force_all"}`
  - Creates scheduler_run record, spawns executor in daemon thread
  - OHLCV stale_only: queries Iceberg for stale tickers, calls `batch_data_refresh()` with only those
  - Other targets: calls registered executor from `backend/jobs/executor.py`
- `GET /admin/data-health/fix/{run_id}/status` — polls progress
  - Returns: `{run_id, status, tickers_total, tickers_done, errors, elapsed_s}`
  - Uses `get_scheduler_run_by_id()` in pg_stocks.py
- `GET /admin/data-health` — health scan (parallelized, ~1.4s)
  - Runs 5 DuckDB queries in ThreadPoolExecutor(max_workers=5)
  - Calls `invalidate_metadata()` before queries to avoid stale reads
  - Returns `total_registry`, `total_analyzable`, `total_financial` for per-card denominators

## Frontend
- `useDataHealth()` hook in `hooks/useAdminData.ts`
  - `triggerFix(target, mode)` — POST + 2s polling interval
  - `fixProgress` / `fixTarget` state for progress tracking
  - Auto-clears 5s after terminal status, calls `mutate()` to refresh
- `DataHealthPanel.tsx` — ProgressBar component, FixBtn on all 5 cards
- Each card uses appropriate total: OHLCV=total_registry, Analytics/Sentiment/Forecast=total_analyzable, Piotroski=total_financial

## Key Files
- `backend/routes.py` — endpoints + health queries
- `backend/db/pg_stocks.py` — `get_scheduler_run_by_id()`
- `stocks/repository.py` — wrapper method
- `frontend/hooks/useAdminData.ts` — hook
- `frontend/components/admin/DataHealthPanel.tsx` — UI
