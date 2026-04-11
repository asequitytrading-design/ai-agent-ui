# Scheduler Runs PostgreSQL Migration

## Why
`update_scheduler_run` on Iceberg did full table scan + overwrite (~9s per call). With 12+ calls per job execution, this dominated pipeline runtime. Iceberg is append-only — not suited for mutable row-level state.

## What Migrated
- `stocks.scheduler_runs` → PostgreSQL `scheduler_runs` table
- `stocks.scheduled_jobs` → already on PG (earlier migration)
- Both Iceberg tables dropped after migration

## Schema (PostgreSQL)
```sql
scheduler_runs (
  run_id VARCHAR(36) PK,
  job_id VARCHAR(36) NOT NULL,
  job_name VARCHAR(200),
  job_type VARCHAR(50),
  scope VARCHAR(20) DEFAULT 'all',
  status VARCHAR(20) DEFAULT 'running',
  started_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ,
  duration_secs FLOAT,
  tickers_total INTEGER DEFAULT 0,
  tickers_done INTEGER DEFAULT 0,
  error_message VARCHAR(500),
  trigger_type VARCHAR(50),
  pipeline_run_id VARCHAR(36)
)
```
Indexes: started_at DESC, job_id, pipeline_run_id, status

## PG CRUD Functions (backend/db/pg_stocks.py)
- `insert_scheduler_run(session, run)`
- `update_scheduler_run_pg(session, run_id, updates)` — single-row UPDATE, <5ms
- `get_scheduler_runs_pg(session, days, filters)` — returns (rows, total)
- `get_scheduler_run_stats_pg(session)` — aggregate counts
- `get_pipeline_run_status_pg(session, pipeline_run_id)`
- `get_last_pipeline_run_id_pg(session, pipeline_id)`
- `get_last_run_for_job_pg(session, job_id)`

## Sync→Async Bridge
Uses `_run_pg()` + `_pg_session()` with NullPool engine. See memory `shared/debugging/asyncpg-sync-async-bridge` for the pattern.

## Performance
- `update_scheduler_run`: 9,000ms → 14ms (640x faster)
- Progress updates restored to per-ticker (was throttled to 30s)
- US forecast pipeline: 55s → 22.8s

## Key Files
- `backend/db/models/scheduler_run.py` — ORM model
- `backend/db/pg_stocks.py` — 7 async CRUD functions
- `stocks/repository.py` — 7 wrapper methods (Iceberg → PG)
- `backend/db/migrations/versions/c4d9e2f1a8b3_add_scheduler_runs.py`
