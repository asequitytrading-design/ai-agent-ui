# System Overview

## Services

| Service | Port | Entry point | Stack |
|---------|------|-------------|-------|
| Backend | 8181 | `backend/main.py` | Python 3.12, FastAPI, LangChain 1.x |
| Frontend | 3000 | `frontend/app/page.tsx` | Next.js 16, React 19, TypeScript |
| Dashboard | 8050 | `dashboard/app.py` | Plotly Dash (FLATLY theme) |
| Docs | 8000 | `mkdocs serve` | MkDocs Material |

## Core Patterns

- **`ChatServer`** (`backend/main.py`) — owns `ToolRegistry`,
  `AgentRegistry`, FastAPI app. All state in this class, no
  module-level mutable globals.
- **`BaseAgent`** (`backend/agents/base.py`) — ABC with agentic loop
  (`MAX_ITERATIONS=15`) + streaming. Subclasses only override
  `_build_llm()`.
- **LLM**: Claude Sonnet 4.6 via `langchain_anthropic.ChatAnthropic`.
  Config in `agents/general_agent.py` and `agents/stock_agent.py`.
- **Streaming**: `POST /chat/stream` returns NDJSON events:
  `thinking`, `tool_start`, `tool_done`, `warning`, `final`, `error`.
- **Same-day cache**:
  `~/.ai-agent-ui/data/cache/{TICKER}_{key}_{YYYY-MM-DD}.txt`.
- **Centralised paths**: `backend/paths.py` — single source of truth
  for all filesystem locations. Override root with `AI_AGENT_UI_HOME`.
- **Tool registration order**: `search_market_news` registered after
  GeneralAgent, before StockAgent.
- **Ticker auto-linking**: `tools/_ticker_linker.py` uses
  `threading.local()` to pass `user_id` from HTTP handler into
  `@tool` functions.
- **Freshness gates**: Analysis skips if done today (Iceberg check);
  forecast skips if run within 7 days. Both non-blocking.

## Filesystem Layout

All runtime data under `~/.ai-agent-ui/` (override: `AI_AGENT_UI_HOME`).
Paths centralised in `backend/paths.py`.

```
~/.ai-agent-ui/
├── data/iceberg/{catalog.db,warehouse/}   # Iceberg tables
├── data/{cache,raw,forecasts,avatars}/     # runtime data
├── charts/{analysis,forecasts}/            # HTML charts
├── logs/                                   # rotating agent.log
├── backend.env                             # secrets (symlinked)
└── frontend.env.local                      # service URLs (symlinked)
```

## Key Directories

- `backend/` — agents, tools, config
- `auth/` — JWT + RBAC + OAuth PKCE + user-ticker linking
- `stocks/` — Iceberg persistence (9 tables, single source of truth)
- `frontend/` — SPA (Next.js)
- `dashboard/` — Dash + services, incl. Marketplace page
- `hooks/` — pre-commit, pre-push
