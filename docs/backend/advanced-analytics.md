# Advanced Analytics — `/v1/advanced-analytics/`

Sprint 9 (Apr-29 → May-02 2026, ASETPLTFRM-340 epic) shipped a
new top-level page **`/advanced-analytics`** for pro and
superuser accounts. Seven NSE-bhavcopy-driven scan reports
sit behind the same shared table component, mirroring the
§5.4 tabular-page-pattern hardened in Sprints 7-8 (Screener,
ScreenQL, RecommendationHistory, Admin Users).

## Route

`/v1/advanced-analytics/<report>` — 7 endpoints.

| Path | Filter (server-side) | Default sort | Cap |
|---|---|---|---|
| `/current-day-upmove` | `today_x_vol > 1 AND current_dpc > avg_20d_dpc` | `today_x_vol DESC` | — |
| `/previous-day-breakout` | `today_x_vol > 1` | `today_x_vol DESC` | — |
| `/mom-volume-delivery` | `x_vol_20d > 1 OR x_dv_20d > 1` | `x_dv_20d DESC` | — |
| `/wow-volume-delivery` | `x_vol_10d > 1 OR x_dv_10d > 1` | `x_dv_10d DESC` | — |
| `/two-day-scan` | `today_x_vol > 1 AND prev_day_x_vol > 1` | `today_x_vol DESC` | — |
| `/three-day-scan` | `today_x_vol > 1 AND prev_day_x_vol > 1` | `today_x_vol DESC` | — |
| `/top-50-delivery-by-qty` | `today_dv > 0` | `today_dv DESC` | top 50 |

### Query params

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | `int ≥ 1` | `1` | Server-side pagination |
| `page_size` | `1 ≤ int ≤ 200` | `25` | Hard cap 200 |
| `sort_key` | `str | null` | Default sort per report | Any field on `AdvancedRow` |
| `sort_dir` | `"asc" \| "desc"` | `"desc"` | Pattern-validated |

### Response shape

```jsonc
{
  "rows": [/* AdvancedRow superset, ~52 nullable fields */],
  "total": 50,
  "page": 1,
  "page_size": 25,
  "stale_tickers": [
    {"ticker": "AAPL", "reason": "missing_delivery"}
  ]
}
```

## Auth + scope

- **`pro_or_superuser` guard** (existing dependency in
  `auth/dependencies.py`, also used by §5.7 scoped admin
  endpoints) — general role gets 403.
- **`_scoped_tickers(user, "discovery")`** (from
  `backend/insights_routes.py`):
    - **Pro / superuser** → full universe
      (`ticker_type IN ('stock', 'etf')`) ∪ watchlist ∪ holdings.
    - **General** never reaches here (403 above), but if it
      did the helper falls back to watchlist ∪ holdings.

## Architecture

**Single-batched DuckDB read per Iceberg table** — no
per-ticker loops (CLAUDE.md §4.1 #1). Per request the
endpoint fans out 8 reads:

```
ohlcv               last 25 trading days per ticker
nse_delivery        last 25 trading days per ticker
technical_indicators latest row per ticker (rsi_14, sma_50, sma_200)
fundamentals_snapshot latest row per ticker (3y/5y CAGR, ROCE, YoY)
promoter_holdings   latest quarter per ticker
corporate_events    latest event per ticker
piotroski_scores    latest score per ticker
company_info        latest snapshot per ticker
```

**EMV-14** is computed inline via
`backend.tools._analysis_indicators.compute_emv_14()` — no
Iceberg column (Sprint 9 AA-1 deviation; the
`technical_indicators` table is the dead persistence path
per system-overview).

## Caching

- Key: `cache:advanced_analytics:<report>:{user_id}:p{page}:s{sort_key|default}:{sort_dir}:ps{page_size}` (per-user — Sprint 7 cross-user leak fix, §5.9).
- TTL: `TTL_STABLE` (300 s).
- Invalidation: `_CACHE_INVALIDATION_MAP` glob `cache:advanced_analytics:*` is fired by every Iceberg write to `nse_delivery`, `promoter_holdings`, `corporate_events`, `fundamentals_snapshot`, `ohlcv`, `technical_indicators` (CLAUDE.md §5.13).

## Stale-ticker transparency chip

Per CLAUDE.md §5.5 each response includes
`stale_tickers: list[StaleTicker]` for any ticker with
missing/NaN required input. Reasons:

| Reason | Trigger |
|---|---|
| `nan_close` | No close price for the latest 25 trading days |
| `missing_delivery` | No row in `nse_delivery` (US stocks, weekends, holidays) |
| `missing_quarterly` | No `fundamentals_snapshot` row |
| `missing_promoter` | No `promoter_holdings` row |

Frontend renders the count as an amber chip in the panel-
title row via `frontend/components/common/StaleTickerChip.tsx`
(extracted from `PLTrendWidget` in Sprint 9 AA-11).

## Frontend

- `/advanced-analytics` route — RSC + `<Suspense fallback={<h1>Advanced Analytics</h1>}>` + `loading.tsx` (text-bearing for FCP heuristic).
- Tab strip + URL sync (`?tab=<id>`).
- Shared `<AdvancedAnalyticsTable>` parameterised by report
  name + column catalog (`columnCatalogs.ts`). Reuses
  `useColumnSelection`, `<ColumnSelector />`,
  `<DownloadCsvButton />`. Locked column: `ticker`.
- Lighthouse on the focused single-route audit:
  **Score 100, LCP 0 ms, FCP 136 ms, TBT 0 ms, CLS 0.000**
  (well under the §5.15 `/analytics/*` budget).

## Data layer

| Iceberg table | Cadence | Source |
|---|---|---|
| `stocks.nse_delivery` | Daily 19:30 IST mon-fri | NSE bhavcopy via `jugaad_data` |
| `stocks.fundamentals_snapshot` | Daily 20:00 IST mon-sat | Aggregated from `quarterly_results` |
| `stocks.promoter_holdings` | Quarterly 04:00 IST 1st of feb/may/aug/nov | BSE shareholding scrape (currently Cloudflare-blocked from dev IP) |
| `stocks.corporate_events` | Daily 07:00 IST mon-sat | NSE corporate-actions feed |

See `stocks/create_tables.py:1296+` for the schemas (`_nse_delivery_schema`, `_promoter_holdings_schema`, `_corporate_events_schema`, `_fundamentals_snapshot_schema`).

## Testing

- **Backend pytest** (27 cases, ~0.6 s):
    - `tests/backend/test_advanced_analytics_routes.py` — 7 happy-path × 7 reports, 7 × 403-for-general, cache short-circuit, pagination, stale_tickers, sort validation, top-50 cap (19 cases).
    - `tests/backend/test_emv_14.py` — 5 EMV-14 reference cases.
    - `tests/backend/pipeline/test_bhavcopy.py` — 3 ingestion cases (one commit per day, skipped on empty, surface `SourceError`).
- **E2E Playwright** (5 cases, ~12 s @ 1 worker) —
  `e2e/tests/frontend/aa-page.spec.ts`, project
  `frontend-chromium` (superuser fixture). Covers default
  load, tab switch + URL sync, CSV button enabled,
  stale chip, pagination round-trip.
- **Frontend** — TypeScript clean, ESLint clean (no new
  errors on AA files; pre-existing test-file drift is
  unrelated).

See `advanced-analytics-rollout.md` (this directory) for
the production rollout SOP.
