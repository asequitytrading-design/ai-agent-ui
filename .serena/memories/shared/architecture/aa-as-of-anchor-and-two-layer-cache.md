# AA as-of anchor + two-layer cache pattern

Discovered while debugging Current Day Upmove returning 0 rows
(commits `8e16144` + `c7c9f9e`). Two related but distinct
patterns now used by every Advanced Analytics endpoint and
worth replicating on any cross-table dashboard reading from
Iceberg.

## Pattern 1 — `as_of` anchor

**Problem**: independent loaders against different Iceberg
tables can land on **different latest dates per row**. AA's
OHLCV (~bulk download to 2026-05-04) and `nse_delivery`
(~latest bhavcopy 2026-04-30) skew → `today_x_vol` from one
date, `current_dpc` from another → dual-condition filters
silently never fire.

**Fix**: query `MAX(date)` from the canonical "drives the
report" table once, and cap every other loader to
`date <= as_of`. Every per-row "today" then describes the
same trading session.

```python
def _effective_trading_date() -> date:
    cache = get_cache()
    cached = cache.get("cache:aa:as_of")
    if cached is not None:
        return date.fromisoformat(str(cached))
    df = _safe_query("stocks.nse_delivery",
                    "SELECT MAX(date) FROM nse_delivery")
    out = ... derive from df, fallback to date.today()
    cache.set("cache:aa:as_of", out.isoformat(), ttl=60)
    return out

# Pass through to every loader:
ohlcv_df = _load_ohlcv_25d(tickers, as_of)
delivery_df = _load_delivery_25d(tickers, as_of)
```

**Critical**: cache `as_of` itself (60 s Redis TTL). Without
this the `MAX(date)` DuckDB scan runs on every request even
when the response is cached, costing ~6 s per call. Cache the
date and the response cache check stays sub-millisecond.

Side benefits:
- Handles weekends, public holidays, long weekends without
  per-report date logic.
- Cache key embeds `as_of` so a fresh bhavcopy ingest
  invalidates yesterday's cache automatically.

Reference: `backend/advanced_analytics_routes.py:206`
(`_effective_trading_date`).

## Pattern 2 — Two-layer cache (rows + response)

**Problem**: a single per-response cache key that includes
filter + sort + page + page_size means any UI interaction
is a full DuckDB recompute. AA was 6 s per filter/sort change.

**Fix**: split into two caches.

| Layer | Key | Value | TTL |
|---|---|---|---|
| Outer rows | `(user_id, as_of)` | full row list (pre-filter, pre-sort) | TTL_STABLE |
| Inner response | `(report, user, market, type, search, as_of, sort, page, ps)` | serialized response body | TTL_STABLE |

```python
async def _cached_full_rows(user, as_of):
    blob = cache.get(f"cache:aa:rows:{user.user_id}:dt{as_of}")
    if blob:
        return [Row(**d) for d in json.loads(blob)]
    rows = build_rows(...)  # DuckDB
    cache.set(..., json.dumps([r.model_dump() for r in rows]),
              ttl=TTL_STABLE)
    return rows

async def _compute_report(user, ..., as_of):
    if hit := cache.get(inner_ck):
        return Response(content=hit)  # fastest
    full = await _cached_full_rows(user, as_of)
    rows = filter + sort + paginate in-memory
    body = build_response(rows)
    cache.set(inner_ck, body, ttl=TTL_STABLE)
    return Response(content=body)
```

Performance (measured):
- Cold (both miss): ~14 s
- Warm same params: ~4 ms
- Sort change (inner miss + outer hit): ~18 ms
- Filter change: ~12 ms
- ~1500× speedup on the warm path

Trade-offs:
- Outer cache size: ~800 rows × ~50 fields ≈ 1 MB per user.
  Acceptable for Pro tier; revisit if user count grows 100×.
- Pydantic round-trip (model_dump → json.dumps → json.loads
  → AdvancedRow(**d)) ~30 ms cost on cache hit; still much
  better than 6 s compute.

Reference: `_cached_full_rows` and `_compute_report` in
`backend/advanced_analytics_routes.py`.

## Operator gotcha

`docker compose restart backend` does NOT pick up changes
to module-level functions referenced in route closures (the
endpoint factory captures `_compute_report` at router-build
time). Use `docker compose up -d --force-recreate backend`
instead. Documented in commit `8e16144` body.

## When to apply this pattern

Any dashboard that:
- Reads from multiple Iceberg tables with potentially
  different latest dates → use `as_of` anchor.
- Shows a tabular view with sort/filter/page that re-renders
  on every UI interaction → use two-layer cache.

NOT needed for:
- Single-table reads (latest-per-ticker is unambiguous)
- Rare endpoints (the cache complexity isn't worth it at
  <100 req/day)
- Fully dynamic queries where the row set changes per request
  (e.g. ScreenQL — its existing per-response cache is fine
  because the query string is the dominant cache key)
