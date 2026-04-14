# ticker_type Classification System

## Overview
The `stock_registry` table has a `ticker_type` column (VARCHAR(20), default "stock", indexed) that classifies tickers into four categories for pipeline filtering.

## Values
| Type | Count | Description | Example |
|------|-------|-------------|---------|
| stock | 755 | Regular equities | RELIANCE.NS, AAPL |
| etf | 54 | Exchange-traded funds | NIFTYBEES.NS, GOLDBEES.NS |
| index | 4 | Market indices | ^NSEI, ^GSPC, ^VIX, ^INDIAVIX |
| commodity | 4 | Futures/commodities | CL=F, ^TNX, ^IRX, DX-Y.NYB |

## Detection Logic
`_detect_ticker_type()` in `backend/tools/_stock_registry.py`:
1. Starts with `^` → "index"
2. Contains `=F` or `.NYB` → "commodity"
3. Has "etf" tag in stock_master → "etf" (cached via `_load_etf_symbols()`)
4. Default → "stock"

## Pipeline Filtering (executor.py)
| Filter | Includes | Used By |
|--------|----------|---------|
| `_analyzable_tickers()` | stock + etf | compute_analytics, run_sentiment, run_forecasts |
| `_has_financials()` | stock only | run_piotroski |
| (no filter) | all | data_refresh (OHLCV) |

## Data Health Totals (routes.py)
- `total_registry` (817) → OHLCV card denominator
- `total_analyzable` (809) → Analytics/Sentiment/Forecast card denominators
- `total_financial` (755) → Piotroski card denominator

## Frontend (analysis/page.tsx)
- Stock Analysis tab: shows all tickers including indices
- Forecast tabs: shows stock + etf only, hides index + commodity
- Auto-redirect: switches to first stock/etf if index selected on forecast tab
- `tickerTypes` state built from registry API `ticker_type` field
