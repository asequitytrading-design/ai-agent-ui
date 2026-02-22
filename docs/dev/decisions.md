# Decisions

A record of the architectural and tooling decisions made during development, and the reasoning behind each one.

---

## Backend Architecture

### OOP refactor — agents/ and tools/ packages

The original backend was two flat files: `main.py` and `agent.py`. `agent.py` defined the LLM, the tools, and the agentic loop all in one place.

The refactor extracted three distinct concerns:

- **`tools/`** — tool definitions and a registry for lookup and invocation.
- **`agents/`** — agent configuration, the agentic loop (in `BaseAgent`), and a registry for routing requests to the correct agent.
- **`main.py`** — wires the two registries together and owns the FastAPI application.

The benefit: adding a new tool or a new agent type requires no changes to any other layer. The registries are the only coupling point.

### ChatServer class in main.py

All server-level state — registries and the FastAPI app — lives inside a `ChatServer` instance rather than as module-level globals. HTTP route handlers are registered as bound methods (`self._chat_handler`), giving them access to the instance's registries without importing anything at module scope.

This makes it trivial to instantiate a second server in tests with a different configuration, and avoids the class of bugs where startup order matters for module-level globals.

### BaseAgent ABC with abstract _build_llm()

The agentic loop is identical across all agent types — convert history, invoke LLM, handle tool calls, repeat. The only thing that varies between agents is the LLM provider and model.

Putting the loop in `BaseAgent` and making `_build_llm()` abstract means:

- The loop logic is tested and maintained in one place.
- Switching from Groq to Claude requires changing two lines in one file (`general_agent.py`), not rewriting the loop.
- Adding a new agent with a different LLM takes ~10 lines of code.

### Switching back to Claude (not yet done)

The intended LLM is Claude Sonnet 4.6. Groq (`openai/gpt-oss-120b`) is a temporary substitute while Anthropic API access is being resolved. The two-line switch is documented in [How to Run](how-to-run.md) and in the `general_agent.py` source file.

---

## Tools

### SerpAPI over Google Custom Search API

SerpAPI was chosen because:

- One API key, no Google Cloud project or OAuth setup required.
- Already supported by `langchain-community` (`SerpAPIWrapper`).
- Free tier (100 searches/month) is sufficient for development.

The tradeoff is that SerpAPI is a paid third-party service, not a direct Google API. For production, a direct integration or a different provider might be preferable.

### search_web error handling with try/except

The original `search_web` tool had no error handling. If SerpAPI was unavailable (missing key, network error, quota exceeded), the exception would propagate up through the agentic loop, cause the HTTP handler to return a `500`, and give the user no useful information.

With try/except, failures become a `ToolMessage` string (`"Search failed: <reason>"`). The LLM receives this as a tool result and can respond gracefully — for example, by acknowledging the failure and answering from training data instead.

---

## Configuration

### Pydantic Settings with lru_cache

Environment variables are validated once at startup through a `Settings(BaseSettings)` model. Benefits:

- Type coercion is automatic (e.g. `LOG_TO_FILE=true` becomes `bool`).
- Missing required fields would raise a clear error at startup, not deep inside a handler.
- `@lru_cache` on `get_settings()` ensures the environment is parsed exactly once.

An optional `.env` file in `backend/` is supported (lower priority than real env vars). This avoids having to `export` variables on every shell session during development.

---

## Logging

### Structured logging over print()

The original code used `print()` for debug output. The refactored backend uses Python's `logging` module throughout, with loggers named after their module (`logging.getLogger(__name__)`).

Benefits over `print()`:

- Log level filtering — set `LOG_LEVEL=WARNING` to suppress debug noise in staging.
- Structured format — timestamp, level, and logger name on every line.
- Consistent output — all modules use the same format automatically.
- File output — rotating file handler captures everything without changing code.

### TimedRotatingFileHandler — daily rotation, 7-day retention

Log files rotate at midnight. The previous 7 days are kept and older files are deleted automatically. This bounds disk usage without requiring a separate log rotation daemon (like `logrotate`).

The `logs/` directory is gitignored so log files are never accidentally committed.

### Clearing handlers on uvicorn hot-reload

uvicorn's `--reload` flag re-imports the application module on file changes. Each import would normally add a new set of handlers to the root logger (doubling, tripling, etc. the output). `setup_logging()` clears all existing handlers before adding new ones:

```python
root_logger.handlers.clear()
```

This is safe because `setup_logging()` always re-adds the correct handlers immediately after clearing.

---

## Python 3.9 Compatibility

The `demoenv` virtualenv runs Python 3.9.13. Two 3.10+ features are avoided:

- **Union type syntax** (`X | Y`, PEP 604) — replaced with `Optional[X]` from `typing`.
- No use of `match` statements (PEP 634).

The codebase does use `list[dict]` and `dict[str, T]` as type hints directly on class attributes. These are valid in Python 3.9 for annotations used at runtime in some contexts, but can cause `TypeError` at runtime if evaluated eagerly. Adding `from __future__ import annotations` to files that use these annotations would make them string-based (deferred evaluation) and fully compatible with 3.9.

---

## Frontend

### Single-file component (page.tsx)

The entire chat UI — state, handlers, and rendering — lives in one file. For a single-page app with one feature, this is appropriate. The overhead of splitting into multiple components and files would add complexity without benefit at this scale.

### Local state only (no Redux, Context, or Zustand)

Three `useState` hooks cover everything the UI needs. There is no shared state between components (there is only one component), so a global state library would be pure overhead.

### Full history sent on every request

The backend is stateless. The frontend sends the complete conversation history with every `POST /chat` request. This is simple and correct — the LLM always has full context.

The tradeoff is that very long conversations send proportionally larger payloads. For a development/demo app this is fine. A production system would likely need server-side session storage.

### axios over fetch

`axios` is used for HTTP requests rather than the native `fetch` API. `axios` throws on non-2xx status codes by default (which is the desired behavior for error handling), has a cleaner API for JSON payloads, and is already a common dependency in the React ecosystem.

---

## Version Control

### Virtualenv excluded from git

`backend/demoenv/` is listed in `.gitignore` as both `demoenv/` and `*env/`. The virtualenv is reconstructable from `requirements.txt`.

### frontend/.git removed

The `frontend/` directory was created with a separate git repo (`.git` subdirectory), which caused the root repo to treat it as a git submodule. The nested `.git` was removed so the frontend is tracked as regular files in the root repo.

### requirements.txt is frozen

`requirements.txt` is populated with `pip freeze` output, pinning exact versions for all direct and transitive dependencies. This ensures reproducible installs. Update it whenever new packages are installed:

```bash
pip freeze > backend/requirements.txt
```
