# Advanced Analytics — pro+superuser tabbed screener page

Sprint 9 (Apr 29 → May 2 2026, ASETPLTFRM-340 epic, 71 SP).
New top-level route `/advanced-analytics` for pro and
superuser accounts. Seven NSE-bhavcopy + fundamentals
scan reports built on top of 4 new Iceberg tables, the
EMV-14 indicator, and the existing piotroski / ohlcv /
technical_indicators / company_info stack.

## Endpoints (`/v1/advanced-analytics/`)

7 GET endpoints with the same `AdvancedReportResponse`
shape (rows, total, page, page_size, stale_tickers):

| Path | Filter | Default sort | Cap |
|---|---|---|---|
| `/current-day-upmove` | `today_x_vol > 1 AND current_dpc > avg_20d_dpc` | `today_x_vol DESC` | — |
| `/previous-day-breakout` | `today_x_vol > 1` | `today_x_vol DESC` | — |
| `/mom-volume-delivery` | `x_vol_20d > 1 OR x_dv_20d > 1` | `x_dv_20d DESC` | — |
| `/wow-volume-delivery` | `x_vol_10d > 1 OR x_dv_10d > 1` | `x_dv_10d DESC` | — |
| `/two-day-scan` | `today_x_vol > 1 AND prev_day_x_vol > 1` | `today_x_vol DESC` | — |
| `/three-day-scan` | `today_x_vol > 1 AND prev_day_x_vol > 1` | `today_x_vol DESC` | — |
| `/top-50-delivery-by-qty` | `today_dv > 0` | `today_dv DESC` | top 50 |

Auth: `pro_or_superuser` (returns 403 for general role).
Scope: `_scoped_tickers(user, "discovery")` from
`backend/insights_routes.py` (pro/superuser see full
universe = `ticker_type IN ('stock', 'etf')` ∪ watchlist
∪ holdings).

## Iceberg tables added

4 new tables (idempotent CREATE in `stocks/create_tables.py`):

| Table | Schema fn | Cadence | Source |
|---|---|---|---|
| `stocks.nse_delivery` | `_nse_delivery_schema` | Daily 19:30 IST mon-fri | NSE bhavcopy via `jugaad_data.nse.full_bhavcopy_raw` |
| `stocks.fundamentals_snapshot` | `_fundamentals_snapshot_schema` | Daily 20:00 IST mon-sat | Aggregated from `quarterly_results` |
| `stocks.promoter_holdings` | `_promoter_holdings_schema` | Quarterly 04:00 IST 1st of feb/may/aug/nov | BSE shareholding (Cloudflare-blocked from dev IP — see rollout SOP) |
| `stocks.corporate_events` | `_corporate_events_schema` | Daily 07:00 IST mon-sat | NSE corporate-actions feed |

Schemas live at `stocks/create_tables.py:1296` (`nse_delivery`),
`:1346` (`promoter_holdings`), `:1399` (`corporate_events`),
`:1441` (`fundamentals_snapshot`).

## EMV-14 indicator

**No Iceberg column.** Persistence was deliberately
deferred (AA-1 deviation): `stocks.technical_indicators`
is the dead persistence path per the system architecture
— the canonical computation lives in
`backend/tools/_analysis_indicators.py::compute_emv_14`
and runs inline per request inside the AA-7 row builder.

Formula:

```
EMV_t  = ((H_t + L_t)/2 - (H_{t-1} + L_{t-1})/2)
         / (V_t / (H_t - L_t))
emv_14 = SMA(EMV, 14)
```

Zero-range candle (`high == low`) coerces to NaN; SMA
naturally skips NaN inputs. Implementation delegates to
`ta.volume.EaseOfMovementIndicator` for the SMA. Empty
DataFrame returns empty Series (no exception). Missing
columns raise `ValueError("compute_emv_14: missing columns ...")`.

## 4 scheduled jobs

Registered via `@register_job` in `backend/jobs/executor.py`
(restart backend after edit per §6.2):

- `nse_bhavcopy_daily` — 19:30 IST mon-fri.
- `fundamentals_snapshot_daily` — 20:00 IST mon-sat.
- `corporate_events_daily` — 07:00 IST mon-sat.
- `promoter_holdings_quarterly` — 04:00 IST on the 1st
  of feb / may / aug / nov.

CLI for one-shot / backfill: `python -m backend.pipeline.runner bhavcopy [--date | --backfill-months N]` plus `fundamentals-snapshot`, `corporate-events`, `promoter-holdings` subcommands.

## Cache invalidation map

`stocks/repository.py::_CACHE_INVALIDATION_MAP` was
extended (AA-8 — already shipped, see commit message for
that ticket):

```python
"stocks.nse_delivery":          ["cache:advanced_analytics:*"],
"stocks.promoter_holdings":     ["cache:advanced_analytics:*"],
"stocks.corporate_events":      ["cache:advanced_analytics:*"],
"stocks.fundamentals_snapshot": ["cache:advanced_analytics:*"],
```

Plus `cache:advanced_analytics:*` was appended to the
existing entries for `stocks.ohlcv` and
`stocks.technical_indicators`. Cache key shape:
`cache:advanced_analytics:<report>:{user_id}:p{page}:s{sort_key|default}:{sort_dir}:ps{page_size}` (per-user keys avoid the Sprint 7 cross-user leak).

TTL: `TTL_STABLE` (300 s).

## Frontend

- Route: `/advanced-analytics` — RSC + `<Suspense fallback={<h1>Advanced Analytics</h1>}>` + `loading.tsx` (text-bearing for FCP heuristic).
- Tab strip + URL sync (`?tab=<id>`) — mirrors the admin tab pattern.
- Shared `<AdvancedAnalyticsTable />` parameterised by
  report name + a column catalog
  (`columnCatalogs.ts`). Each tab is a 3-15 line
  wrapper. Reuses `useColumnSelection`,
  `<ColumnSelector lockedKeys={['ticker']} />`, and
  `<DownloadCsvButton />`.
- Nav entry gated by new `proOrSuperuserOnly` flag on
  `NavItem` (added to both `Sidebar.canSeeItem` and
  `NavigationMenu.canSeeItem`).
- `<StaleTickerChip />` now lives at
  `frontend/components/common/StaleTickerChip.tsx`
  (extracted from `PLTrendWidget.tsx` in AA-11). The
  generic API takes `items: { key, primary, secondary }[]`
  + summary/tooltip strings; both PLTrend and AA call
  sites adapt their data into the common shape.

Lighthouse on the focused single-route audit (mobile
baseline, simulated 4× CPU / slow 4G):
**Score 100, LCP 0 ms, FCP 136 ms, TBT 0 ms, CLS 0.000**.
Well under the §5.15 `/analytics/*` budget.

## Tests

- **Backend (27 cases, ~0.6 s)**:
  `tests/backend/test_advanced_analytics_routes.py` (19
  cases — 7 happy × 7 reports, 7 × 403, cache short-
  circuit, pagination, stale_tickers, sort validation,
  top-50 cap), `tests/backend/test_emv_14.py` (5 cases),
  `tests/backend/pipeline/test_bhavcopy.py` (3 cases).
  Mocks `_scoped_tickers`, `_safe_query`, `get_cache` —
  no Iceberg / Redis / PG required.
- **E2E (5 cases, ~12 s)**:
  `e2e/tests/frontend/aa-page.spec.ts` (renamed from
  `advanced-analytics.spec.ts` so the filename doesn't
  collide with the greedy `/analytics.*\.spec\.ts/`
  regex used by `analytics-chromium` testMatch — the
  spec needs the superuser storageState).

## Production rollout

`docs/backend/advanced-analytics-rollout.md` is the
SOP (squash-merge → `docker compose restart backend` →
`redis-cli FLUSHALL` → 6 mo bhavcopy backfill →
fundamentals-snapshot rebuild → 7-endpoint smoke +
nav-gate browser smoke + 24 h watch).

## When to read this memory

- Adding a new Advanced Analytics report tab (new column,
  new filter, new sort default).
- Modifying any AA endpoint (`pro_or_superuser` guard,
  cache key shape, `stale_tickers` reasons).
- Touching the EMV-14 helper or any `compute_emv_14`
  consumer.
- Adding a new scheduled job in the bhavcopy /
  fundamentals / corporate-events / promoter family.
- Editing `_CACHE_INVALIDATION_MAP` for any of the four
  new tables.
- Re-running the production rollout SOP.

## Cross-references

- §5.4 tabular-page-pattern · `tabular-page-pattern`
- §5.5 stale-ticker chip · `portfolio-pl-stale-ticker-chip`
- §5.13 redis cache layer · `redis-cache-layer`
- §5.15 perf budgets · `lighthouse-performance-workflow`
- §5.7 scope-aware admin (parent pattern) ·
  `pro-user-role-scoped-admin`
- §5.9 insights ticker scoping · `_scoped_tickers` in
  `backend/insights_routes.py`
