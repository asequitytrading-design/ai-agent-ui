# PROGRESS.md — Session Log

---

# Session: Feb 28, 2026 — Iceberg stock storage + Insights dashboard pages

## What We Built

Full Apache Iceberg persistence layer for all stock market data (8 tables), dual-write hooks in every backend tool, a one-time backfill script, 6 new Insights pages in the dashboard, and auto-init in `run.sh`.

### Phase 1 — `stocks/` package skeleton

| File | Purpose |
|------|---------|
| `stocks/__init__.py` | Package docstring |
| `stocks/create_tables.py` | Idempotent init of 8 `stocks.*` Iceberg tables |

### Phase 2 — `stocks/repository.py`

`StockRepository` class with full CRUD for all 8 tables:

| Table | Key methods |
|-------|-------------|
| `stocks.registry` | `upsert_registry`, `get_registry` |
| `stocks.company_info` | `insert_company_info`, `get_latest_company_info`, `get_all_latest_company_info` |
| `stocks.ohlcv` | `insert_ohlcv`, `get_ohlcv`, `get_latest_ohlcv_date` |
| `stocks.dividends` | `insert_dividends`, `get_dividends` |
| `stocks.technical_indicators` | `upsert_technical_indicators`, `get_technical_indicators` |
| `stocks.analysis_summary` | `insert_analysis_summary`, `get_latest_analysis_summary`, `get_all_latest_analysis_summary`, `get_analysis_history` |
| `stocks.forecast_runs` | `insert_forecast_run`, `get_latest_forecast_run` |
| `stocks.forecasts` | `insert_forecast_series`, `get_latest_forecast_series` |

### Phase 3 — Dual-write in backend tools

Added lazy `_get_repo()` singleton + Iceberg writes to:

- `backend/tools/stock_data_tool.py` — OHLCV on fetch + delta, registry upsert, company info, dividends
- `backend/tools/price_analysis_tool.py` — technical indicators + analysis summary
- `backend/tools/forecasting_tool.py` — forecast run metadata + full forecast series

All writes wrapped in `try/except`; failures logged as `WARNING` and never break existing tool behaviour.

### Phase 4 — `stocks/backfill.py`

8-step idempotent backfill of all existing flat files into Iceberg. Run once per deployment after `create_tables.py`. Steps: registry → company_info → ohlcv → dividends → technical_indicators → analysis_summary → forecasts → forecast_runs.

### Phase 5 — 6 Insights dashboard pages

| Page | Route | Iceberg source |
|------|-------|----------------|
| Screener | `/screener` | `analysis_summary` (fallback: flat parquet) |
| Price Targets | `/targets` | `forecast_runs` |
| Dividends | `/dividends` | `dividends` |
| Risk Metrics | `/risk` | `analysis_summary` |
| Sectors | `/sectors` | `company_info` + `analysis_summary` |
| Correlation | `/correlation` | `ohlcv` (fallback: flat parquet) |

Changes: `dashboard/layouts.py` (NAVBAR Insights dropdown + 6 layout functions), `dashboard/callbacks.py` (`_get_iceberg_repo()` + 6 callbacks), `dashboard/app.py` (imports + 6 routes).

### Phase 6 — Infrastructure + docs

- `run.sh` — `_init_stocks()` function; called after `_init_auth()` on every `./run.sh start`
- `mkdocs.yml` — "Iceberg Storage" page added under Stock Agent nav
- `docs/backend/stocks_iceberg.md` — full reference: tables, API, backfill, quirks, Insights pages

### Files changed

| File | Change |
|------|--------|
| `stocks/__init__.py` | New |
| `stocks/create_tables.py` | New |
| `stocks/repository.py` | New |
| `stocks/backfill.py` | New |
| `backend/tools/stock_data_tool.py` | Dual-write: OHLCV, registry, company_info, dividends |
| `backend/tools/price_analysis_tool.py` | Dual-write: technical_indicators, analysis_summary |
| `backend/tools/forecasting_tool.py` | Dual-write: forecast_run, forecast_series |
| `dashboard/callbacks.py` | `dbc` import, `_get_iceberg_repo()`, 6 Insights callbacks |
| `dashboard/layouts.py` | NAVBAR Insights dropdown, 6 layout functions |
| `dashboard/app.py` | 6 new routes |
| `run.sh` | `_init_stocks()` added |
| `mkdocs.yml` | Iceberg Storage page added |
| `docs/backend/stocks_iceberg.md` | New |
| `PROGRESS.md` | This entry |
| `CLAUDE.md` | `stocks/` package + Iceberg decisions |

---

# Session: Feb 28, 2026 — Post-merge branch cleanup + CI auto-delete workflow

## What We Did

Housekeeping session after PR #3 (`feature/test-branch` → `dev`) was merged.

### 1. Deleted merged local + remote branches

| Branch | Reason |
|--------|--------|
| `feature/test-branch` | Merged via PR #3 → dev |
| `chore/remove-details-txt` | Merged via PR #2 → main |
| `claude/beautiful-clarke` | Local-only Claude worktree (no PR) |
| `claude/wonderful-driscoll` | Local-only Claude worktree (no PR) |

Remote branches `origin/feature/test-branch`, `origin/chore/remove-details-txt`, `origin/claude/wonderful-driscoll` deleted via `git push origin --delete`.

### 2. Updated CLAUDE.md project tree

Removed stale entries `STOCK_AGENT_PLAN.md` and `details.txt` (both previously deleted).

### 3. Created `.github/workflows/cleanup.yml`

Auto-deletes source branch when a PR is merged. Skips protected branches (`main`, `dev`, `qa`, `release`, `gh-pages`).

### Files changed

| File | Change |
|------|--------|
| `PROGRESS.md` | This entry |
| `CLAUDE.md` | Removed stale file entries from project tree |
| `.github/workflows/cleanup.yml` | New — auto-delete branch on PR merge |

---

# Session: Feb 27, 2026 — Branching strategy + Pre-commit hook improvements

## What We Built

### 1. Branching strategy

Created `dev`, `qa`, `release` branches. Full `feature/* → dev → qa → release → main` CI/CD workflow.

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Per-branch CI jobs (dev/qa/release/main) |
| `.github/CODEOWNERS` | Reviewer groups per merge path |
| `.github/pull_request_template.md` | Standard PR checklist |

### 2. Pre-commit hook: Groq → Claude

`hooks/pre_commit_checks.py` now uses Anthropic SDK (`claude-sonnet-4-6`). `has_llm` → `has_claude`; `GROQ_API_KEY` → `ANTHROPIC_API_KEY`.

### 3. Pre-commit: mkdocs build validation

`_run_mkdocs_build()` runs after doc patches; warn-only (non-blocking). `import shutil` added.

### 4. Branch-aware pre-commit

Detects branch via `git symbolic-ref --short HEAD`; warns on direct commits to `main`/`qa`/`release`. Exports `GIT_CURRENT_BRANCH`; banner shows `(branch: <name>)`.

### Files changed

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | New |
| `.github/CODEOWNERS` | New |
| `.github/pull_request_template.md` | New |
| `hooks/pre-commit` | Branch detection + GIT_CURRENT_BRANCH export |
| `hooks/pre_commit_checks.py` | Groq → Anthropic; has_claude; _run_mkdocs_build(); import shutil |

---

# Condensed history — Feb 21–26, 2026

| Date | What was built | Key commit(s) |
|------|---------------|---------------|
| Feb 26 | Google + Facebook SSO (OAuth2 PKCE). `auth/oauth_service.py`, `auth/migrate_users_table.py`, PKCE helpers in `frontend/lib/oauth.ts`, callback page, SSO buttons on login page. Google live; Facebook needs real credentials. | — |
| Feb 25 (auth hardening) | Auth Phase 6: `scripts/seed_admin.py`, `run.sh _init_auth()`, `docs/backend/auth.md`, mkdocs build passes. Two deploy fixes: JWT env propagation in `main.py`; `_load_dotenv()` in `dashboard/app.py`. Superuser seeded. | — |
| Feb 25 (admin UI) | Auth Phase 5: `/admin/users` Dash page (Users + Audit Log tabs), Change Password modal, `_api_call()` helper, token propagation via `?token=`. Admin nav item in Next.js for superusers. | — |
| Feb 25 (dashboard UX) | Home market filter (India/US), pagination + page-size selector, admin table search + pagination. Pre-commit hook created (`hooks/pre-commit` + `hooks/pre_commit_checks.py`). | — |
| Feb 24 (auth phases 1–4) | Iceberg tables (`auth/create_tables.py`, `auth/repository.py`), AuthService + JWT (`auth/service.py`, `auth/models.py`, `auth/dependencies.py`), 12 API endpoints (`auth/api.py`), Next.js auth guard + login page + `apiFetch`. | — |
| Feb 24 (streaming + UX) | `POST /chat/stream` NDJSON streaming, request timeout (120s), dashboard light theme (FLATLY), iframe `X-Frame-Options: ALLOWALL`, dynamic currency symbols (₹/$/£/€ etc.), SPA navigation with internal link routing, bottom-right FAB. | `be09863`, `5c017f2` |
| Feb 23 (dashboard) | Plotly Dash dashboard (`dashboard/`): Home/Analysis/Forecast/Compare pages, callbacks, custom CSS, `run_dashboard.sh`. | — |
| Feb 23 (stock agent) | StockAgent + 8 stock tools (Yahoo Finance, Prophet forecasts, technical analysis, charts, agent-to-agent news tool). Per-agent history, same-day cache. | `895df0f` |
| Feb 22 | OOP backend refactor: `agents/` + `tools/` packages, `ChatServer`, `BaseAgent`, `ToolRegistry`, `AgentRegistry`, structured logging, Pydantic Settings, MkDocs site (11 pages), pre-push hook. | `fa20966`, `f7f1cbc` |
| Feb 21 | Initial app: FastAPI + LangChain agentic loop, Next.js chat UI, Groq LLM (Claude Sonnet 4.6 intended), `search_web` (SerpAPI), multi-turn history, first GitHub push. | `6604b74`, `ee7967f`, `ef643f7` |
