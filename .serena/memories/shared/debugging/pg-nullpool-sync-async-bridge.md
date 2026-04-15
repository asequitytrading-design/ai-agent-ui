# NullPool Pattern for Sync→Async PG Bridge

## Problem
`StockRepository` is called from sync threads (scheduler, pipeline executor, batch jobs) but PG queries are async (SQLAlchemy asyncpg). Two issues:
1. `asyncio.run()` creates a new event loop per call — pooled connections bound to the old loop can't be reused ("Future attached to different loop")
2. Thread-local engines leak connections when threads terminate — exhausts `max_connections`

## Solution: NullPool
`_pg_session()` in `stocks/repository.py` uses `NullPool` — each session gets a fresh TCP connection and releases it on close. No pool, no loop binding, no leaks.

```python
def _pg_session():
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory()
```

## Trade-off
- ~2-5ms per call (TCP connect overhead)
- Zero leaked connections (vs 11+ with thread-local pools)
- Safe across any number of threads and event loops

## When to use
- All `_run_pg()` calls from sync context (repository methods)
- FastAPI async endpoints use the shared `get_engine()` from `engine.py` instead (pooled, same loop)

## PG max_connections
Increased from 20 to 50 in `docker-compose.yml` to handle 5 forecast workers + FastAPI pool + scheduler threads.

## Key insight
For hot paths, avoid per-call PG sessions — use DuckDB batch reads or bulk PG writes. NullPool is fine for infrequent updates (scheduler progress, finalize).
