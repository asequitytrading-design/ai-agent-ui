# Stock Chart — Support & Resistance Lines

**Date:** 2026-05-05
**Status:** Design — awaiting plan
**Owner:** Abhay Singh
**Related code:** `frontend/components/charts/StockChart.tsx`, `backend/dashboard_routes.py`, `backend/tools/_analysis_movement.py`

---

## 1. Problem

The Stock Analysis page (`/analytics/analysis` → Chart tab) renders a TradingView lightweight-charts candle pane with SMAs, Bollinger Bands, RSI and MACD. Traders inspecting a ticker have no way to see structural support / resistance levels overlaid on the chart, which is the most common request when reading price action.

The data already exists. `_analyse_price_movement` in `backend/tools/_analysis_movement.py` computes 3 support and 3 resistance levels per ticker (lowest 3 lows and highest 3 highs from the trailing 252 trading days) and writes them as a serialized string into the `technical_indicators_summary` Iceberg table. They are currently consumed only by the `price_analysis_tool` chat tool — never surfaced in the UI.

## 2. Goal

Render the existing 3 support and 3 resistance levels as horizontal price lines on the candle pane, behind a toggle in the existing Indicators dropdown, with right-edge price tags styled like the current RSI 70/30 references.

## 3. Non-goals (explicitly deferred)

- User-selectable timeframe dropdown (3M / 5Y / All) — fixed 1Y for v1.
- Pivot points, Fibonacci retracements, swing-high S/R, or any second source of levels.
- "Visible-range" follow-zoom mode that recomputes as the user pans.
- Crosshair-tooltip "Near R1" hover annotation.
- A separate S/R chip / list near the chart header (chart-only for v1).
- Forecast tab — only the Chart tab gets the overlay.
- Schema evolution on the Iceberg table — reuse existing serialized columns.

## 4. UX

### 4.1 Toggle

Add a single `Support/Resistance` checkbox to the existing Indicators dropdown menu in `analytics/analysis/page.tsx`. Default **OFF**. Same checkbox affordance, same `data-testid` pattern (`stock-analysis-indicator-supportResistance`).

### 4.2 Lines

Six dashed horizontal lines drawn on the candle series via TradingView's `createPriceLine()` API — same call already used for the RSI 70/30 reference lines in `StockChart.tsx`.

| Property | Value |
|---|---|
| Resistance color | `#ef4444` (matches existing red accent) |
| Support color | `#10b981` (matches existing green accent) |
| Line style | Dashed |
| Line width | 1 |
| `axisLabelVisible` | `true` |
| `priceLineVisible` | `true` |
| `title` | tier label — `R1` / `R2` / `R3` / `S1` / `S2` / `S3` |

Tier labels follow the standard convention: **R1 / S1 = nearest to current price**, R2/S2 next, R3/S3 furthest. R1/R2/R3 are above the latest close; S1/S2/S3 are below. The tag rendered on the right edge contains `<tier> <price>` (e.g. `R1 2580`). Percentage-distance is intentionally omitted from v1 (deferred).

### 4.3 Behavior across chart interactions

- **Interval switch (D / W / M):** levels stay the same. They are absolute price levels, not bar-aggregations, so they do not depend on candle aggregation.
- **Toggle OFF then ON:** lines re-rendered from cached arrays. No re-fetch.
- **Theme toggle (light/dark):** colors unchanged (red/green readable on both themes; existing `isDark` prop already handles series-level theming).
- **Ticker change:** new SWR fetch returns new arrays; existing chart-cleanup effect removes old price lines before drawing new.

## 5. Backend

### 5.1 Endpoint shape

Extend the **existing** `GET /v1/dashboard/chart/indicators?ticker=…` endpoint in `backend/dashboard_routes.py`. Do **not** add a new endpoint.

```jsonc
// IndicatorsResponse — additions only
{
  "ticker": "RELIANCE.NS",
  "data": [ /* IndicatorPoint[], unchanged */ ],
  "support_levels":    [1950.0, 2080.0, 2210.0],   // sorted ASC,  length 0-3
  "resistance_levels": [2840.0, 2710.0, 2580.0]    // sorted DESC, length 0-3
}
```

Both fields are `list[float]` with length 0–3. Empty when OHLCV history is too thin or the ticker is unknown. Sort direction matches the existing `_analyse_price_movement` output exactly (`support_levels` ASC, `resistance_levels` DESC) so the frontend can rely on order without re-sorting.

### 5.2 Implementation

In the route handler:

1. After `df = compute_indicators(t_upper)` already loads the daily OHLCV-with-indicators DataFrame, call `_analyse_price_movement(df)` once.
2. Read `support_levels` and `resistance_levels` from its return dict.
3. Pass them into `IndicatorsResponse` alongside the existing `data` points.

The Pydantic `IndicatorsResponse` model gains two `list[float] = []` fields (default empty list, not `None`, to keep the frontend contract simple).

### 5.3 Cache

Reuse the existing `cache:chart:indicators:{ticker}` Redis key with `TTL_STABLE = 300s`. Write-through invalidation is already wired via `_CACHE_INVALIDATION_MAP` whenever the per-ticker refresh writes to the indicators tables (CLAUDE.md §5.1, §5.13). The new fields ride along — no new map entry required.

### 5.4 Cost

`_analyse_price_movement` is a pure pandas function on a DataFrame that is already in memory. Wall cost is ~1 ms per request. No additional Iceberg or DuckDB read.

## 6. Frontend

### 6.1 Types — `frontend/components/charts/StockChart.types.ts`

Add to `IndicatorVisibility`:
```ts
supportResistance: boolean;
```

Add to `DEFAULT_INDICATORS`:
```ts
supportResistance: false,
```

### 6.2 Chart — `frontend/components/charts/StockChart.tsx`

- Accept two new optional props on the chart component: `supportLevels?: number[]` and `resistanceLevels?: number[]`.
- Inside the existing chart-build effect, after the candle series is created, conditionally call `candleSeries.createPriceLine(...)` once per level when `visibleIndicators.supportResistance` is `true` and the array is non-empty.
- Compute tier labels client-side from the latest close on the chart (already known to the component): nearest level above = `R1`, next = `R2`, furthest = `R3`; mirrored for S.
- Hold the returned `IPriceLine` refs in a local array and call `candleSeries.removePriceLine(line)` on cleanup or when the toggle flips off.
- No changes to the Volume / RSI / MACD panes.

### 6.3 Page — `frontend/app/(authenticated)/analytics/analysis/page.tsx`

- Extend the SWR / `useEffect` fetch around line 291 (`chart/indicators`) to also extract `support_levels` and `resistance_levels` from the response and store them in component state alongside `chartIndicators`.
- Add `{ key: "supportResistance", label: "Support/Resistance" }` to `INDICATOR_OPTIONS`.
- Pass `supportLevels` and `resistanceLevels` props into `<StockChart …>`.
- Add `data-testid="stock-analysis-indicator-supportResistance"` on the new checkbox label (matching the existing convention in §5.14 of CLAUDE.md).

## 7. Edge cases

| Case | Behavior |
|---|---|
| OHLCV history < 252 bars (newly listed) | `_analyse_price_movement` returns whatever `nsmallest(3)` / `nlargest(3)` produce on the shorter series. If `len(df) < 6`, arrays may be shorter than 3 — frontend tolerates. |
| Empty OHLCV / unknown ticker | Endpoint returns 200 with `support_levels: []`, `resistance_levels: []`. Chart silently draws nothing. No error toast. |
| Latest close pierces a level | Tier labels recomputed each render against the latest close. A pierced R1 simply becomes the new S1 (or vice versa). Self-correcting. |
| Two levels equal after rounding | Not deduplicated. `nsmallest(3)` / `nlargest(3)` are stable. |
| Toggle flipped while data still loading | `supportLevels` / `resistanceLevels` are `undefined` until SWR resolves; chart effect treats `undefined` as "draw nothing" → no flash. |
| Ticker changes while toggle is on | Existing chart-rebuild effect tears down old price lines via the stored refs before the new candle series is mounted. |
| Pre-1980 epoch dates | Already filtered upstream in OHLCV (CLAUDE.md §6.5). Not a concern here. |

## 8. Testing

### 8.1 Backend pytest

Extend (or create) `tests/test_dashboard_chart.py`:

1. Happy path — ticker with full history → response includes 3 ascending supports + 3 descending resistances.
2. New listing — ticker with ~50 bars → both arrays present, length ≤ 3.
3. Empty OHLCV — unknown ticker → both arrays empty, 200 OK, no exception.
4. Cache hit — two calls; `_analyse_price_movement` called once. Mock at the source module per CLAUDE.md §4.2 #16.

### 8.2 Frontend Vitest

`frontend/components/charts/StockChart.test.tsx`:

- When `visibleIndicators.supportResistance = true` and arrays each contain 3 levels → `candleSeries.createPriceLine` is invoked 6 times with correct titles `S1`/`S2`/`S3`/`R1`/`R2`/`R3` keyed by proximity to the latest close.
- When the toggle is `false` → `createPriceLine` is **not** invoked for S/R (existing RSI 70/30 calls untouched).
- Toggle off → `removePriceLine` invoked for the 6 stored refs.

### 8.3 Playwright E2E

`e2e/specs/analytics-analysis-sr-toggle.spec.ts`:

- Selector registered in `e2e/utils/selectors.ts` `FE.stockAnalysisIndicatorSupportResistance` = `[data-testid="stock-analysis-indicator-supportResistance"]`.
- Page object method `toggleSupportResistance()` on the existing `AnalysisPage`.
- Spec — load analysis page for a known seeded ticker, open Indicators dropdown, click S/R toggle, assert presence of 6 price-tag DOM nodes (TradingView's price labels — match by text starting with `R1`, `R2`, `R3`, `S1`, `S2`, `S3`). Toggle off → 0 such nodes.

Single worker locally per CLAUDE.md §5.14.

## 9. Performance budget

- Backend: +1 ms per `chart/indicators` request, no new Iceberg / DuckDB I/O, no new Redis key.
- Response payload: +~80 bytes.
- Frontend bundle: 0 bytes (lightweight-charts already loaded; `createPriceLine` is part of the existing API surface).
- LCP on `/analytics/analysis`: unchanged. Per-route budget (CLAUDE.md §5.15) untouched.

## 10. Rollout

1. Deploy backend first. Existing frontends ignore the new fields.
2. Deploy frontend second. Backend restart required because `IndicatorsResponse` gained fields (CLAUDE.md §6.2).
3. After backend deploy, `redis-cli FLUSHALL` is **not** required (existing cached JSON without the new fields will simply omit the arrays; frontend tolerates missing → empty → no lines). Optional flush for cleanliness.

## 11. Open follow-ups (post-ship)

- Window selector dropdown next to the toggle (3M / 1Y / 5Y / All).
- % distance on hover via crosshair.
- Pivot-point and Fibonacci-retracement layers as additional Indicators entries.
- Surface S/R in a small chart-header chip alongside the existing tier badges.
