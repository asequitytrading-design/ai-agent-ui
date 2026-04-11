# Project Index: AI Agent UI

> AI-agent-optimised codebase map. For human onboarding, see `docs/`.
> Last refreshed: 2026-04-12 (Sprint 6 — Forecast Optimization + Scheduler)

---

## Project Structure

```
ai-agent-ui/
├── backend/               # FastAPI application (:8181)
│   ├── main.py            # Entry point
│   ├── agents/            # LangChain agentic framework (14 files)
│   ├── tools/             # Stock analysis tools (20+ files)
│   ├── jobs/              # Scheduler executors + pipeline (5 files)
│   ├── pipeline/          # CLI data pipeline (19 commands)
│   ├── db/                # ORM models, migrations, DuckDB
│   │   ├── models/        # 12 SQLAlchemy models
│   │   ├── migrations/    # Alembic async migrations
│   │   ├── engine.py      # Async session factory
│   │   ├── duckdb_engine.py # Iceberg read engine + metadata cache
│   │   └── pg_stocks.py   # PG CRUD (registry, scheduler, pipeline)
│   ├── config.py          # Settings (Pydantic)
│   ├── routes.py          # Admin API + data-health endpoints
│   ├── dashboard_routes.py # Dashboard/chart API
│   ├── insights_routes.py # Screener/analytics API
│   └── llm_fallback.py    # N-tier LLM cascade (Groq → Ollama → Anthropic)
├── auth/                  # JWT + RBAC + OAuth PKCE
├── stocks/                # Iceberg repository (5,000+ lines)
├── frontend/              # Next.js 16 SPA (:3000)
│   ├── app/               # 12 pages (App Router)
│   ├── components/        # 30+ components (admin, charts, insights, widgets)
│   ├── hooks/             # 19 SWR data hooks
│   └── lib/               # Types, config, apiFetch
├── e2e/                   # 54 Playwright specs (~219 tests)
├── tests/                 # 83 pytest files (~755 tests)
├── scripts/               # 30 data/migration/seed scripts
├── docs/                  # 48 MkDocs Material pages
└── docker-compose.yml     # 5 services (backend, frontend, PG, Redis, docs)
```

---

## Entry Points

| Entry | Path | Port |
|-------|------|------|
| Backend API | `backend/main.py` | 8181 |
| Frontend SPA | `frontend/app/page.tsx` | 3000 |
| Pipeline CLI | `backend/pipeline/runner.py` | — |
| Scheduler | `backend/jobs/scheduler_service.py` | daemon |
| Docs | `docs/` via MkDocs | 8000 |

---

## Database (Hybrid PG + Iceberg)

**PostgreSQL (13 tables)**: users, user_tickers, payments, registry,
scheduled_jobs, scheduler_runs, user_memories (pgvector 768-dim),
stock_master, stock_tags, ingestion_cursor, ingestion_skipped,
pipelines, pipeline_steps.

**Iceberg (12 tables)**: ohlcv (1.4M rows), company_info, dividends,
quarterly_results, analysis_summary, forecast_runs, forecasts,
piotroski_scores, sentiment_scores, llm_pricing, llm_usage,
portfolio_transactions.

**Rule**: Mutable state → PG. Append-only analytics → Iceberg.
DuckDB for all Iceberg reads (metadata cache, auto-invalidated).

---

## Key Modules

| Module | Files | Purpose |
|--------|-------|---------|
| `backend/agents/` | 14 | LangChain ReAct agent, intent routing, multi-turn |
| `backend/tools/` | 20+ | Stock tools: forecast, analysis, sentiment, portfolio |
| `backend/jobs/` | 5 | Executor registry, pipeline chaining, batch refresh |
| `backend/pipeline/` | 8 | CLI: download, seed, bulk-download, analytics, forecast |
| `backend/db/models/` | 12 | SQLAlchemy ORM (PG tables) |
| `stocks/repository.py` | 1 (5K lines) | Iceberg CRUD + DuckDB reads + PG bridge |
| `frontend/hooks/` | 19 | SWR data fetching for all pages |
| `frontend/components/admin/` | 6 | Scheduler, Pipeline, DataHealth, PipelineForm |

---

## Scheduler & Jobs

5 job types: `data_refresh`, `compute_analytics`, `run_sentiment`,
`run_forecasts`, `run_piotroski`. All accept `force=False`.

Freshness gates: daily (OHLCV, analytics, sentiment), weekly
(forecasts), monthly (CV accuracy auto-refresh via 30-day TTL).

Pipeline: sequential steps with skip-on-failure. India (4 steps,
~10 min) and USA (4 steps, ~2 min) daily pipelines.

Performance: batch DuckDB reads, bulk Iceberg writes,
`workers = cpu_count // 2`, `parallel=None` for Prophet CV.

---

## Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| FastAPI | 0.135 | REST API |
| Next.js | 16.1 | Frontend |
| LangChain | 1.2 | Agent framework |
| Prophet | 1.3 + CmdStanPy 1.3 | Forecasting |
| SQLAlchemy | 2.0 async | ORM (asyncpg) |
| PyIceberg | 0.11 | Table management |
| SWR | 2.3 | Frontend data hooks |
| lightweight-charts | 5.1 | TradingView |

---

## File Counts

Python: 214 | TypeScript: 118 | Tests: 83+10+54 | Docs: 48 | Scripts: 30

---

## Quick Start

```bash
cp .env.example .env && ./run.sh start
docker compose exec backend python scripts/seed_demo_data.py
# http://localhost:3000 → admin@demo.com / Admin123!
```
