# Market Ticker — Header Inline Design Spec

**Date:** 2026-04-13
**Status:** Approved
**Branch:** feature/sprint6

---

## Overview

Real-time Nifty 50 and Sensex ticker displayed inline in the center
of the AppHeader for authenticated users. Updates every 30 seconds
during market hours. Serves persisted data outside market hours with
zero upstream calls.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Placement | Inline header center | No extra vertical space; empty center gap exists |
| Visibility | Authenticated only | Header lives inside `AuthenticatedShell` |
| Auth | JWT-protected endpoint | Consistent with `/v1/` API pattern |
| Indices | Nifty 50 + Sensex only | Two indices fit header comfortably |
| Refresh | 30s polling | Balance between freshness and rate limits |
| Persistence | Redis (hot) + PostgreSQL (cold) | Survives restart and Redis flush |
| Off-market | Serve PG data, zero upstream calls | No pinging NSE/Yahoo after 15:30 IST |

## Backend

### Endpoint

```
GET /v1/market/indices
Authorization: Bearer <JWT>
```

**Response (200):**

```json
{
  "nifty": {
    "price": 23886.30,
    "change": 164.30,
    "change_pct": 0.69,
    "prev_close": 23722.00,
    "open": 23589.60,
    "high": 23907.40,
    "low": 23555.60
  },
  "sensex": {
    "price": 76986.46,
    "change": -563.79,
    "change_pct": -0.73,
    "prev_close": 77550.25,
    "open": 77100.00,
    "high": 77200.00,
    "low": 76800.00
  },
  "market_state": "REGULAR",
  "timestamp": "2026-04-13T14:51:00+05:30",
  "stale": false
}
```

`market_state` values: `"REGULAR"`, `"CLOSED"`, `"PRE"`, `"POST"`.

When `stale: true`, the data is from PG persistence (upstream
unreachable). Frontend should still display it normally.

**Error (503):** No cached or persisted data available at all
(fresh install, never fetched).

### Route File

**New file: `backend/market_routes.py`**

- `MarketIndexRouter` with single `GET /` endpoint.
- Registered in `backend/routes.py` as `prefix="/v1/market"`.

### Upstream Sources

#### NSE India (Nifty 50)

- Endpoint: `https://www.nseindia.com/api/allIndices`
- Auth: Cookie-based session. Hit `https://www.nseindia.com` first
  to get session cookies, then use them for API calls.
- Requires `User-Agent` header (browser-like).
- Parse `data` array, find entry where `index == "NIFTY 50"`.
- Fields: `last`, `variation`, `percentChange`, `open`, `high`,
  `low`, `previousClose`.
- Use `requests.Session()` with cookie persistence. Refresh
  session on 403/401.

#### Yahoo Finance (Sensex)

- Endpoint: `https://query2.finance.yahoo.com/v7/finance/quote?symbols=^BSESN`
- Auth: Cookie + crumb flow.
  1. GET `https://fc.yahoo.com` → extract cookies.
  2. GET `https://query2.finance.yahoo.com/v1/test/getcrumb`
     with cookies → get crumb token.
  3. Append `&crumb={crumb}` to quote URL.
- Fields: `regularMarketPrice`, `regularMarketChange`,
  `regularMarketChangePercent`, `regularMarketOpen`,
  `regularMarketDayHigh`, `regularMarketDayLow`,
  `regularMarketPreviousClose`, `marketState`.
- Refresh crumb on 401.

### Caching Strategy

```
Request flow:
  1. Check Redis key `market:indices` (TTL 30s)
  2. HIT  → return cached JSON
  3. MISS → check market hours
     a. Market open  → fetch NSE + Yahoo concurrently
                      → merge → store Redis (30s TTL)
                      → upsert PG → return
     b. Market closed → read from PG → store Redis (300s TTL)
                       → return with market_state="CLOSED"
```

- **Redis key:** `market:indices`, value is the full JSON response.
- **Redis TTL:** 30s during market hours, 300s outside market hours.
- **PG table:** `market_indices` — single-row upsert on every
  successful upstream fetch. Cold fallback for restart/Redis flush.

### Market Hours Gating

Market hours: **Monday–Friday, 09:00–15:30 IST**.

```python
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    market_open = now.replace(hour=9, minute=0, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    return market_open <= now <= market_close
```

When `is_market_open()` returns `False`:
- Do NOT call NSE India or Yahoo Finance.
- Serve PG-persisted data. Override `market_state` to `"CLOSED"`
  regardless of what was stored (avoids stale "REGULAR" after
  a mid-session restart).
- Redis TTL extended to 300s (no point refreshing frequently).

During market hours, `market_state` is taken from Yahoo's
`marketState` field (`REGULAR`, `PRE`, `POST`).

### PostgreSQL Model

**New file: `backend/db/models/market_index.py`**

```
Table: market_indices
  id              INTEGER PRIMARY KEY DEFAULT 1
  nifty_data      JSONB NOT NULL
  sensex_data     JSONB NOT NULL
  market_state    VARCHAR(10) NOT NULL
  fetched_at      TIMESTAMPTZ NOT NULL
  CHECK (id = 1)  -- single-row constraint
```

- Single row, always `id=1`. Upserted via
  `INSERT ... ON CONFLICT (id) DO UPDATE`.
- `nifty_data` and `sensex_data` are JSONB containing
  `price`, `change`, `change_pct`, `prev_close`, `open`,
  `high`, `low`.
- Alembic migration required.

### Error Handling

| Failure | Behavior |
|---------|----------|
| NSE session expired | Auto-refresh session cookies, retry once |
| Yahoo crumb expired | Re-fetch crumb, retry once |
| NSE returns non-200 | Use Yahoo for Nifty (`^NSEI`) as fallback |
| Yahoo returns non-200 | Use NSE-only data (Sensex omitted) |
| Both upstreams fail | Serve PG-persisted data with `stale: true` |
| Redis down | Fall through to PG directly |
| PG has no row (fresh install) | Return 503 |

### Concurrency

Fetch NSE and Yahoo concurrently using `asyncio.gather()`.
Timeout each upstream at 10 seconds. If one times out, return
whatever the other provides + PG fallback for the missing index.

## Frontend

### Component

**New file: `frontend/components/MarketTicker.tsx`**

- Renders in AppHeader center gap.
- CSS: `hidden md:flex` — hidden on mobile (< 768px).
- Polls `GET /v1/market/indices` via `apiFetch` every 30s
  using `setInterval` inside `useEffect`.
- Fetches immediately on mount, then every 30s.

### Display

```
NIFTY  23,886.30  ▲ 164.30 (+0.69%)  |  SENSEX  76,986.46  ▼ 563.79 (-0.73%)
```

- Index name: muted gray (`text-gray-400`).
- Price: white/dark text, monospace, `font-semibold`.
- Change: green (`text-green-500`) for positive, red
  (`text-red-500`) for negative. Triangle ▲/▼ prefix.
- Separator: muted vertical bar.
- Font size: `text-xs` (12px) to fit comfortably.

### States

| State | Display |
|-------|---------|
| Loading (initial) | `"Market data loading..."` in muted italic |
| Data (market open) | Full ticker with green/red changes |
| Data (market closed) | Price + muted "Closed" label instead of change |
| Data (stale) | Same as normal display (no visual difference) |
| Error (no data ever) | Component renders nothing (hidden) |

### Dark Mode

Inherits from AppHeader's existing `dark:` classes. No special
handling needed — gray/green/red work in both themes.

## Files

| File | Action | Description |
|------|--------|-------------|
| `backend/market_routes.py` | Create | Endpoint, NSE/Yahoo fetchers, cache logic |
| `backend/routes.py` | Edit | Register `/v1/market` router |
| `backend/db/models/market_index.py` | Create | `market_indices` ORM model |
| `backend/db/migrations/xxxx_market_indices.py` | Create | Alembic migration |
| `frontend/components/MarketTicker.tsx` | Create | Ticker display component |
| `frontend/components/AppHeader.tsx` | Edit | Add `<MarketTicker />` in center |

## Testing

- Backend: mock NSE/Yahoo responses, verify cache hit/miss,
  verify market hours gating, verify PG fallback on upstream
  failure.
- Frontend: verify renders correctly with mock data, verify
  hidden on mobile, verify polling interval.

## Out of Scope

- Bank Nifty or other indices.
- WebSocket real-time feed.
- Unauthenticated/landing page ticker.
- Historical intraday chart in header.
