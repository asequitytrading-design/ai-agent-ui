# Advanced Analytics — Production Rollout SOP

Runbook for cutting Sprint 9 Advanced Analytics
(ASETPLTFRM-340 epic) over to production. Use this in
order; every step is idempotent and can be re-run safely.

## 1 · Pre-merge gates

```bash
# Backend lint + tests (pytest now baked into the backend
# image via requirements-dev.txt — see ASETPLTFRM-357 #1):
docker compose exec backend bash -lc \
  "cd /app && python -m pytest \
    tests/backend/test_advanced_analytics_routes.py \
    tests/backend/test_emv_14.py \
    tests/backend/test_etf_classification.py \
    tests/backend/pipeline/test_bhavcopy.py"

# Frontend typecheck + lint:
cd frontend && npx tsc --noEmit -p . && \
  npx eslint app/\(authenticated\)/advanced-analytics/ \
    components/advanced-analytics/ \
    components/common/StaleTickerChip.tsx \
    hooks/useAdvancedAnalyticsData.ts \
    lib/types/advancedAnalytics.ts

# E2E (1 worker, frontend-chromium project):
cd e2e && npx playwright test --project=frontend-chromium \
  --grep "Advanced Analytics" --workers=1

# Lighthouse on /advanced-analytics (focused single-route):
PERF_TEST_EMAIL=admin@demo.com PERF_TEST_PASSWORD=*** \
  node scripts/perf-check-auth.js
# Expect: Score 100, LCP 0ms, FCP <300ms, TBT 0ms, CLS 0.000.

# Optional: full 34-route Lighthouse pass before prod cutover:
docker compose --profile perf build frontend-perf
docker compose --profile perf up -d \
  postgres redis backend frontend-perf
docker compose --profile perf run --rm perf
# Output: frontend/.lighthouseci/pw-lh-summary.json — verify
# /advanced-analytics row stays within /analytics/* bucket
# (Perf ≥ 75, LCP ≤ 3000ms, CLS ≤ 0.1, TBT ≤ 200ms).
```

## 2 · Squash-merge to `dev`

Per CLAUDE.md §4.4 #26 — squash only.

```bash
gh pr merge <pr#> --squash
```

## 3 · Production cutover steps

### 3.1 · Restart backend (CLAUDE.md §6.2)

```bash
docker compose restart backend
sleep 5
```

Required because:
- New router (`backend/advanced_analytics_routes.py` — `app.include_router` only re-registers on app build).
- New Pydantic models (`AdvancedReportResponse`, etc.).
- New scheduled jobs (`@register_job` decorators in `backend/jobs/executor.py` for `nse_bhavcopy_daily`, `fundamentals_snapshot_daily`, `promoter_holdings_quarterly`, `corporate_events_daily`).

### 3.2 · Redis flush (one-shot, schema evolution)

```bash
docker compose exec redis redis-cli FLUSHALL
```

Required because the AA-1 `add_column("emv_14", DoubleType())` was
**not** applied (compute-only — see AA-1 deviation note in
`shared/architecture/project_advanced_analytics.md`). FLUSHALL is
still recommended once because the AA-8 cache invalidation map
gained `cache:advanced_analytics:*` glob entries; pre-existing
`cache:dashboard:home:*` and similar keys are unaffected.

### 3.3 · 6-month bhavcopy backfill

Sequential, ~6 minutes (180 trading days × ~2 s each):

```bash
docker compose exec backend bash -lc \
  "PYTHONPATH=.:backend python -m backend.pipeline.runner \
     bhavcopy --backfill-months 6"
```

Expect: ~450 k rows in `stocks.nse_delivery` (~2,500 tickers
× 180 trading days). Holiday days surface as
`status="skipped"` (NSE returns empty body).

### 3.4 · Fundamentals snapshot rebuild

```bash
docker compose exec backend bash -lc \
  "PYTHONPATH=.:backend python -m backend.pipeline.runner \
     fundamentals-snapshot"
```

Expect: ~700-2 k rows (one per active stock-master ticker)
in `stocks.fundamentals_snapshot`. Note: 3 y / 5 y CAGR
columns will be sparsely populated until
`quarterly_results` has more depth — they auto-fill on
subsequent daily runs as the quarterly history grows.

### 3.5 · Corporate events daily ingest (manual one-shot if needed)

```bash
docker compose exec backend bash -lc \
  "PYTHONPATH=.:backend python -m backend.pipeline.runner \
     corporate-events"
```

Otherwise the scheduled job at 07:00 IST mon-sat handles it.

### 3.6 · Promoter holdings (quarterly, manual one-shot)

The BSE shareholding endpoint is currently 302-redirected from
the dev IP (Cloudflare bot deflection). For production:

- Ensure the production egress IP is allowlisted by BSE, OR
- Route via an allowed proxy, OR
- Defer to the paid BSE API and replace
  `BseShareholdingSource` accordingly.

Until then, `stocks.promoter_holdings` stays empty and the
chip surfaces `missing_promoter` on every ticker — that's
expected and not a regression.

```bash
# Once unblocked:
docker compose exec backend bash -lc \
  "PYTHONPATH=.:backend python -m backend.pipeline.runner \
     promoter-holdings"
```

### 3.7 · ETF registry classification (one-shot)

Required so the AA `?ticker_type=etf` filter returns rows.
Without this, every row in `stocks.stock_registry` has
`ticker_type='stock'` (default) — including known NSE ETFs
(NIFTYBEES.NS, GOLDBEES.NS, BANKBEES.NS, TATAGOLD.NS, …).
Fixed structurally per ASETPLTFRM-357 #5 — going forward,
`backend/pipeline/jobs/ohlcv.py` calls
`_detect_ticker_type()` on every refresh — but the existing
rows need a one-shot backfill on cutover.

```bash
# Step 1 — seed the 54 NSE ETFs into stock_master + tags
# (idempotent; --update keeps existing rows in place).
docker compose exec backend bash -lc \
  "PYTHONPATH=.:backend python -m backend.pipeline.runner \
     seed --csv data/universe/nse_etfs.csv --update"

# Step 2 — restart backend so the cached _etf_symbols set
# in backend.tools._stock_registry picks up the new tags.
docker compose restart backend
sleep 5

# Step 3 — backfill stock_registry.ticker_type='etf' for the
# 54 ETFs by joining stock_master ↔ stock_tags.
docker compose exec postgres psql -U postgres -d aiagent \
  -c "UPDATE stocks.stock_registry
      SET    ticker_type = 'etf'
      WHERE  REPLACE(REPLACE(ticker, '.NS', ''), '.BO', '')
             IN (SELECT s.symbol
                 FROM   stocks.stock_master s
                 JOIN   stocks.stock_tags  st
                        ON st.stock_id = s.id
                 WHERE  st.tag = 'etf'
                 AND    st.removed_at IS NULL);"

# Step 4 — verify
docker compose exec -T backend python -c "
from insights_routes import _get_stock_repo
reg = _get_stock_repo().get_all_registry()
etfs = [t for t,m in reg.items()
        if str(m.get('ticker_type','')).lower()=='etf']
print('total:', len(reg), 'etfs:', len(etfs))
"
# Expect: total: 800+, etfs: 50+
```

Subsequent OHLCV refreshes preserve `ticker_type='etf'`
automatically (the pipeline now calls
`_detect_ticker_type()` on every upsert).

### 3.8 · Promoter holdings quarterly schedule

Schedules the BSE promoter-holdings ingest to run monthly
on the 25th at 04:00 IST. Each non-quarter month is a
no-op (scoped delete + reinsert of the same quarter end).
Currently a no-op even on quarter months — BSE Cloudflare-
blocks the dev IP (see ASETPLTFRM-358); will start
producing data automatically once an allowlisted egress
is in place (no code change).

```bash
docker compose exec postgres psql -U app -d aiagent <<'SQL'
INSERT INTO public.scheduled_jobs
  (job_id, name, job_type, cron_days, cron_time,
   cron_dates, scope, enabled, force)
VALUES
  (gen_random_uuid()::text,
   'Promoter Holdings - India',
   'promoter_holdings_quarterly',
   'mon,tue,wed,thu,fri,sat,sun',
   '04:00',
   '25',
   'india',
   true,
   false)
ON CONFLICT (name) DO NOTHING;
SQL

docker compose restart backend  # scheduler reloads jobs
```

Verify via `/v1/admin/scheduler/jobs` — the job should
report `next_run: <next 25th> 04:00 IST`.

## 4 · Smoke tests

### 4.1 · API smoke (hit each of 7 endpoints)

```bash
TOKEN=$(curl -s -X POST http://localhost:8181/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.com","password":"Admin123!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

for ep in current-day-upmove previous-day-breakout \
          mom-volume-delivery wow-volume-delivery \
          two-day-scan three-day-scan \
          top-50-delivery-by-qty; do
  curl -s -o /tmp/aa.json \
    -w "  $ep → %{http_code} time=%{time_total}s" \
    -H "Authorization: Bearer $TOKEN" \
    "http://localhost:8181/v1/advanced-analytics/$ep?page=1&page_size=5"
  python3 -c "import json;d=json.load(open('/tmp/aa.json'));\
    print(' rows=',len(d.get('rows',[])),\
    'total=',d.get('total'),\
    'stale=',len(d.get('stale_tickers',[])))"
done
```

Expected: all 200, latency < 2 s cold / < 50 ms warm,
non-zero `total` for at least 5 of 7 reports once the
6-month backfill is in.

### 4.2 · 403 smoke (general user)

```bash
GEN_TOKEN=$(curl -s -X POST http://localhost:8181/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@demo.com","password":"Test1234!"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

for ep in current-day-upmove previous-day-breakout \
          mom-volume-delivery wow-volume-delivery \
          two-day-scan three-day-scan \
          top-50-delivery-by-qty; do
  st=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $GEN_TOKEN" \
    "http://localhost:8181/v1/advanced-analytics/$ep?page=1")
  echo "  $ep → $st"
done
```

Expected: all 403.

### 4.3 · Browser smoke

- Login as **superuser** → "Advanced Analytics" link in
  sidebar (between Analytics and Admin) → click → all 7
  tabs render → switch tab → URL syncs `?tab=...` → CSV
  button enabled → stale-ticker chip visible.
- Login as **general** → no "Advanced Analytics" link in
  sidebar; direct GET to `/advanced-analytics` is gated by
  the proxy + backend 403.

## 5 · 24 h post-deploy watch

Confirm:
- Sentry / observability has no new error rate spike.
- Scheduler tab in `/admin` shows green runs for all 4 new
  jobs (`nse_bhavcopy_daily` 19:30 IST, `fundamentals_snapshot_daily`
  20:00 IST, `corporate_events_daily` 07:00 IST, and on the
  1st of feb/may/aug/nov also `promoter_holdings_quarterly`
  04:00 IST).
- DuckDB row counts on the four new Iceberg tables stay
  within sane bounds (`nse_delivery` accumulates ~2,500
  rows/day; the others are bounded).
- Cache hit rate on `cache:advanced_analytics:*` settles
  high after the first ~5 minutes.

## 6 · Rollback

If a regression surfaces:

```bash
# Roll the route off without reverting code:
gh workflow run kill-switch.yml -f route=/v1/advanced-analytics
# (or)  comment out the include_router line in
#       backend/routes.py and restart backend.

# Frontend nav can be hidden by reverting AA-9
# (frontend/lib/constants.tsx + NavigationMenu/Sidebar
# canSeeItem branches).

# Backend tables (nse_delivery, etc.) are append-only
# Iceberg — no schema migration to undo. They can be
# left in place; the pipeline jobs are independently
# enable/disableable from /admin/scheduler.
```
