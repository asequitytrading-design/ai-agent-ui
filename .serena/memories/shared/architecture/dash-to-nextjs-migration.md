# Dash-to-Next.js Migration Status (Mar 18, 2026)

## Fully Migrated (Native Next.js)
| Page | Route | Status |
|------|-------|--------|
| Portfolio (Dashboard Home) | `/dashboard` | Native — asymmetric widget grid |
| Analytics Home | `/analytics` | Native — stock cards + search |
| Analysis | `/analytics/analysis` | Native — TradingView chart (lightweight-charts v5) |
| Forecast | `/analytics/analysis?tab=forecast` | Native — tab in analysis page |
| Compare | `/analytics/analysis?tab=compare` | Native — tab in analysis page |
| Insights (7 tabs) | `/analytics/insights` | Native — InsightsTable + Plotly |
| Link Ticker | `/analytics/marketplace` | Native — registry browser |
| Admin (3 tabs) | `/admin` | Native — users + audit + LLM observability |

## Still on Iframe
| Page | Route | Status |
|------|-------|--------|
| `/insights` | Redirect → `/analytics/insights` | Iframe REMOVED, redirects to native |
| `/docs` | iframe → MkDocs (port 8000) | Keep — separate static site |

## Iframe Cleanup Done
- `/insights/page.tsx` — replaced with `redirect("/analytics/insights")`
- `IFrameView.tsx` component — kept (still used by `/docs`)
- `DASHBOARD_URL` config — kept (used by ChatPanel link detection)

## Architectural Differences (Dash vs Next.js)
- Dash: in-process data access (0 network hops, 5-min TTL cache)
- Next.js: Browser → FastAPI → Redis/Iceberg (2 hops, mitigated by Redis cache)
- Solution: Redis write-through cache + SWR browser cache = sub-100ms on hit

## Chart Library
- Analysis page: `lightweight-charts` v5 (TradingView, ~45 KB)
- Forecast/Correlation/Insights: `plotly.js-basic-dist` (kept for fill-between, heatmap)
