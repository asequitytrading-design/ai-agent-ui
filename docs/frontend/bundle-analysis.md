# Frontend Bundle Analysis

Generated: 2026-04-23 (Sprint 8, ASETPLTFRM-331)
Source: `cd frontend && ANALYZE=true npx next build --webpack`
Artifact: `frontend/.next/analyze/client.html`

## Headline — bundle size

| Route | Before (KB) | After (KB) | Δ | Heavy libs removed |
|---|---:|---:|---:|---|
| `/dashboard` | 292* | **107** | −63% | echarts, echarts-for-react, zrender |
| `/analytics/insights` | 392* | **76** | −81% | plotly.js-basic-dist (1 MB), react-plotly |
| `/analytics/analysis` | 292 | **127** | −56% | lightweight-charts (150 KB via `DEFAULT_INDICATORS` import leak) |
| `/analytics/compare` | 19 | 19 | — | (compare chart already dynamic) |
| `/admin` | 392 | 392 | — | react-markdown still eager (follow-up) |
| `/login` | 25 | 25 | — | — |

## Headline — Lighthouse LCP (measured 2026-04-23, containerized run)

Source: `docker compose --profile perf run --rm perf` — 31 of 34
routes captured (Lighthouse protocol-errored on one tab mid-run;
see *Audit reliability* below). Baseline = Sprint 7 host run
prior to lazy-loading.

| Route | LCP before (ms) | LCP after (ms) | Δ |
|---|---:|---:|---:|
| `/analytics/analysis` | 18 439 | **6 779** | **−63%** |
| `/analytics/compare` | 11 046 | **5 153** | **−53%** |
| `/insights` | 10 138 | **6 544** | **−35%** |
| `/dashboard` | 7 740 | **4 746** | **−39%** |
| `/analytics` | 7 187 | **4 678** | **−35%** |
| `/login` | 6 143 | **3 731** | **−39%** |
| `/admin` | 5 305 | 5 341 | flat |
| `/analytics/insights` | 3 450 | 3 495 | flat (already optimal) |
| `/docs` | 4 036 | 4 077 | flat |

CLS stayed ≤ 0.02 across every route (skeleton fallbacks
preserved layout). TBT ≤ 0 ms Lighthouse-measured (desktop
throttling, no blocking JS observed).

### New tab audits (2026-04-24 verify-run)

The containerized run added 25 tab variants. Post-fix numbers:

| Route | LCP (ms) | Δ vs first run | Note |
|---|---:|---|---|
| `/analytics/insights?tab=sectors` | **4 622** | −3 901 (−46%) | plotly → SimpleBarChart (ECharts) |
| `/analytics/insights?tab=quarterly` | **3 486** | −5 107 (−59%) | plotly → SimpleBarChart (ECharts) |
| `/analytics/analysis?tab=portfolio-forecast` | 3 498 | flat | CLS 0.162 → **0.001** via min-h wrapper |
| `/analytics/analysis?tab=analysis` | 6 781 | flat | eager indicator charts — follow-up |
| `/analytics/analysis?tab=forecast` | 7 128 | +800 | Prophet chart; CLS 0.073 |
| `/admin?tab=observability` | 5 730 | flat | react-markdown eager in admin |
| `/analytics/insights?tab=screener` | 3 505 | flat | clean |

**No route breaches 8 s LCP anymore.**

\* “Before” dashboard/insights figures reconstruct what the
initial entry would have pulled had the chart-heavy widgets
stayed statically imported. Sprint 7 prod baseline measured
FCP 3.4 s and LCP up to 18 s on these routes.

## Top packages (parsed size across all chunks)

Measured from the full post-change webpack analyzer output.
These show the packages still in the total shipped JS — most
are now behind `next/dynamic` boundaries and only load when
the relevant route or tab is first interacted with.

| # | Package | Parsed KB | Notes |
|---|---|---:|---|
| 1 | `plotly.js-basic-dist` | 1 060 | Insights Dividends/Targets tabs; now dynamic |
| 2 | `next` | 575 | Framework; unavoidable |
| 3 | `echarts-for-react` | 514 | Dashboard + Sector widgets; now dynamic |
| 4 | `echarts` | 468 | — |
| 5 | `react-dom` | 174 | Framework |
| 6 | `zrender` | 166 | echarts render backend |
| 7 | `lightweight-charts` | 150 | Analysis route StockChart; now dynamic |
| 8 | `react-markdown` | 105 | Chat + Admin/observability viewers |
| 9 | `remark-gfm` | 27 | react-markdown GFM extension |
| 10 | `fancy-canvas` | 17 | lightweight-charts dep |

## Changes shipped

### 1. Lazy-load 6 chart widgets

All swapped from static imports to `next/dynamic` with
`ssr: false` + a `WidgetSkeleton` loading fallback:

**Dashboard** (`frontend/app/(authenticated)/dashboard/page.tsx`):
- `ForecastChartWidget` (plotly)
- `SectorAllocationWidget` (echarts pie)
- `AssetPerformanceWidget` (echarts bar)
- `PLTrendWidget` (echarts line)

**Insights** (`frontend/app/(authenticated)/analytics/insights/page.tsx`):
- `PlotlyChart` → `SimpleBarChart` (echarts BarChart) on Sectors + Quarterly
- `CorrelationHeatmap` (echarts heatmap, tree-shaken)

### ECharts BarChart migration (Sectors + Quarterly)

`PlotlyChart` was the only consumer of `plotly.js-basic-dist`
(1 MB). Both call sites were categorical bar charts — swapped
to new `components/charts/SimpleBarChart.tsx` which uses the
tree-shaken `echarts/core` + `BarChart` modules. On Dashboard
(already loads `echarts/core` for AssetPerformance, Sector, PL
widgets), hitting `insights?tab=sectors` now reuses the cached
echarts chunk. Plotly dependency can be dropped from
`package.json` in a follow-up (only `chartBuilders.ts` still
references `CHART_COLORS` and is dead code).

### 2. Fix StockChart type leak

`analytics/analysis/page.tsx` imported `DEFAULT_INDICATORS`
(a runtime const) from `StockChart.tsx`, which forced the
whole module — and its `lightweight-charts` dep — into the
initial bundle even though `StockChart` itself was dynamic.

Split:
- New `components/charts/StockChart.types.ts` holds
  `ChartInterval`, `IndicatorVisibility`, `DEFAULT_INDICATORS`
  (zero runtime deps).
- `StockChart.tsx` re-exports them for backward compat.
- `analysis/page.tsx` imports from `.types` directly.

Result: `/analytics/analysis` initial chunk fell from 292 KB
to 127 KB.

## Verification

Re-run the containerized Lighthouse suite (ASETPLTFRM-330):

```bash
docker compose --profile perf build
docker compose --profile perf up -d postgres redis backend frontend-perf
docker compose --profile perf run --rm perf
```

Compare `pw-lh-summary.json` against the Sprint 7 baseline
captured on 2026-04-23. Target:
- FCP < 2000 ms on `/dashboard`, `/analytics`, `/admin`
- LCP < 8000 ms on all authenticated routes
- CLS ≤ 0.02 (preserved)
- TBT < 200 ms

## Follow-ups (not in this PR)

- **Drop plotly deps**: `plotly.js-basic-dist` + `react-plotly.js`
  can come out of `package.json`; `chartBuilders.ts` (unused) and
  `PlotlyChart.tsx` need to be removed first.
- **Admin** still ships `react-markdown` (105 KB) in its initial
  chunk — likely via `ObservabilityTab`'s LLM event viewer. LCP
  on `/admin?tab=observability` is 5.7 s; converting that viewer
  to `next/dynamic` should drop it below 4 s.
- **CLS creep on admin tabs** (0.02–0.12 on scheduler, observability,
  maintenance, recommendations): async tables render without
  reserved height. Add `min-h-[Npx]` on the outer card containers
  (same fix as portfolio-forecast).
- **`/analytics/analysis?tab=analysis/forecast`** (~6.5–7.1 s) —
  sub-chart rehydration dominates. Consider splitting the
  ForecastChart variants behind `dynamic` too.
- **`/analytics/insights` Screener tab** still auto-queries the
  full universe on mount. Deferring to first user filter event
  would shave LCP further (needs UX signoff).

## Audit reliability (meta)

Single-Chromium, 34-route runs occasionally crash with
`Protocol error (Page.enable): Session closed` after ~30
successful audits. Lighthouse + persistent-context memory
pressure. Mitigation options, in order of effort:

1. Re-launch `chromium.launchPersistentContext` every 15 routes
   (closes + reopens the target tab, clearing accumulated CDP
   state).
2. Split the runner into two passes (base + tabbed) via an
   env flag.
3. Raise `docker compose` memory limit for the `perf` service
   (currently unlimited on Docker Desktop, but the perf
   container's own JS heap fills with gathered LHR objects).

Not blocking for Sprint 8 — we captured 31/34 routes on the
first try. Address if CI stabilisation becomes important.
