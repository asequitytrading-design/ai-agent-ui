# Per-Ticker Refresh Pipeline (Dashboard)

## Backend API
- `POST /v1/dashboard/refresh/{ticker}` — starts background refresh
- `GET /v1/dashboard/refresh/{ticker}/status` — polls status (idle/pending/success/error)

## Implementation
- Uses `RefreshManager` from `dashboard/callbacks/refresh_state.py` (ThreadPoolExecutor, max 2 workers)
- Calls `run_full_refresh(ticker, horizon_months=9)` from `dashboard/services/stock_refresh.py`

## 6-Step Pipeline (`run_full_refresh`)
1. **OHLCV fetch** — full re-fetch from yfinance, Iceberg dedup on (ticker, date) — CRITICAL
2. **Company info** — `stock_data_tool.get_stock_info()` — non-critical
3. **Dividends** — `stock_data_tool.get_dividend_history()` — non-critical
4. **Technical analysis** — `price_analysis_tool.analyse_stock_price()` — non-critical
5. **Quarterly results** — `stock_data_tool.fetch_quarterly_results()` — non-critical
6. **Prophet forecast** — trains model, computes MAE/RMSE/MAPE, saves to forecast_runs + forecasts — CRITICAL

## Skip Conditions
- OHLCV: skipped if today's data already exists
- Forecast: skipped if last run < 7 days old

## Frontend: `WatchlistWidget.tsx`
Per-ticker refresh icon on each row:
- ↻ (idle) → spinner (pending, polls every 2s) → ✓ (success, 3s) → ↻
- On success: calls `onRefresh()` to reload dashboard data via SWR mutate
- On error: shows ✗ for 5s then resets

## Cache Invalidation
On successful refresh, invalidates all related cache keys:
`cache:dash:*`, `cache:chart:ohlcv:{ticker}`, `cache:chart:indicators:{ticker}`,
`cache:chart:forecast:{ticker}:*`, `cache:insights:*`
