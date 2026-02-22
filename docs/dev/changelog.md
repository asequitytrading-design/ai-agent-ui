# Changelog

Session-by-session record of what was built, changed, and fixed.

---

## Feb 22, 2026

### OOP Backend Refactor

Deleted `backend/agent.py` and replaced it with a proper package structure.

**New files:**

| File | Description |
|------|-------------|
| `backend/agents/__init__.py` | Package marker |
| `backend/agents/base.py` | `AgentConfig` dataclass + `BaseAgent` ABC with full agentic loop |
| `backend/agents/registry.py` | `AgentRegistry` — maps agent IDs to agent instances |
| `backend/agents/general_agent.py` | `GeneralAgent(BaseAgent)` + `create_general_agent` factory |
| `backend/tools/__init__.py` | Package marker |
| `backend/tools/registry.py` | `ToolRegistry` — maps tool names to `BaseTool` instances |
| `backend/tools/time_tool.py` | `get_current_time` `@tool` |
| `backend/tools/search_tool.py` | `search_web` `@tool` (with try/except) |
| `backend/config.py` | `Settings(BaseSettings)` with `@lru_cache` singleton |
| `backend/logging_config.py` | `setup_logging()` — console + rotating file handler |

**Rewritten:**

- `backend/main.py` — full rewrite as `ChatServer` class; added `GET /agents` endpoint; `POST /chat` now accepts `agent_id` and returns it in the response; errors now raise `HTTPException` (404/500) instead of returning error strings in 200 bodies.

**Updated:**

- `.gitignore` — added `logs/` entry.
- `CLAUDE.md` — full sync with new file tree, API shapes, new decisions.
- `PROGRESS.md` — Feb 22 session log added.

**Commit:** `fa20966` — *refactor: OOP backend restructure with agents/, tools/ packages and structured logging*

---

### MkDocs Setup

- Installed `mkdocs==1.6.1` and `mkdocs-material==9.7.2` into `demoenv`.
- Created `mkdocs.yml` with material theme (indigo, light/dark toggle), navigation tabs, code copy buttons, and full nav tree.
- Created `docs/` directory structure with all pages.

---

## Feb 21, 2026

### Initial Build

Built the complete application from scratch in a single session.

**Backend (`backend/main.py`, `backend/agent.py`):**

- FastAPI server with CORS open to all origins.
- `POST /chat` endpoint accepting `message` and `history`.
- LangChain agentic loop in `run_agent()`: invokes LLM → executes tool calls → feeds `ToolMessage` results back → repeats until no tool calls → returns `response.content`.
- Two tools: `get_current_time` and `search_web`.

**Frontend (`frontend/app/page.tsx`):**

- Single-page chat UI with message bubbles, avatars, timestamps, typing indicator, auto-growing textarea.
- Full conversation history sent with every request.
- Error state shown in the chat bubble on network failure.

**LLM history:**

| Commit | LLM | Reason |
|--------|-----|--------|
| `6604b74` | Claude Sonnet 4.6 | Initial implementation |
| `ee7967f` | Groq `openai/gpt-oss-120b` | Anthropic API not working during testing |
| `ef643f7` | Groq (unchanged) | Added real SerpAPI search tool |

**Commits:**

| Hash | Message |
|------|---------|
| `6604b74` | Initial commit: agentic chat app with Claude Sonnet 4.6 |
| `ee7967f` | chore: swap LLM back to Groq (openai/gpt-oss-120b) for testing |
| `ef643f7` | feat: implement search_web tool with SerpAPI (real Google results) |
| `89d7eb4` | docs: update CLAUDE.md and add PROGRESS.md session log |

---

## Known Issues / Pending Work

| Issue | Priority | Notes |
|-------|----------|-------|
| Anthropic API not working | High | Switch back once access is fixed — see [How to Run](how-to-run.md) |
| No iteration cap on agentic loop | Medium | Misbehaving LLM could loop forever |
| Backend URL hardcoded in frontend | Medium | Move to `NEXT_PUBLIC_BACKEND_URL` in `.env.local` |
| No request timeout on frontend | Medium | Long agent loops block the UI indefinitely |
| No streaming | Low | Full response appears at once; SSE/WebSockets would improve UX |
| No session persistence | Low | Page refresh clears conversation |
| `agent_id` not exposed in UI | Low | Frontend always uses default `"general"` agent |
