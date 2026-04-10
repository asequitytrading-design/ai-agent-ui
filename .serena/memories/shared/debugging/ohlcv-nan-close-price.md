# OHLCV NaN Close Price Issue

## Problem
Batch refresh running during market hours fetches rows with valid open/high/low/volume but `close=NaN` (market not yet closed). These NaN rows then trick the freshness check (`MAX(date) >= yesterday` → skip) on subsequent runs, blocking re-fetch of proper closing data.

## Root Cause
yfinance `history()` returns intraday data with NaN close when market is still open. The freshness query `SELECT MAX(date) FROM ohlcv` doesn't exclude NaN rows.

## Fix (2026-04-10)
1. **`_get_fetch_end_date()`** in `batch_refresh.py`: Before 17:30 IST → `end=today` (exclude today). After 17:30 IST → `end=tomorrow` (include today). 2h buffer after NSE close (15:30) for data settlement.
2. **Freshness query** excludes NaN: `WHERE close IS NOT NULL AND NOT isnan(close)`.
3. **Screener** drops NaN close before picking latest price: `ohlcv_df.dropna(subset=["close"])`.

## Key Insight
204 tickers had NaN close on 2026-04-09 because batch ran during market hours. Always use `end=` parameter in yfinance to prevent partial data from entering Iceberg.
