# PROGRESS.md — Session Summary (Feb 21, 2026)

---

## What We Did Today

### 1. Migrated LLM from Groq → Claude Sonnet 4.6
- Replaced `langchain_groq.ChatGroq` with `langchain_anthropic.ChatAnthropic`
- Model set to `claude-sonnet-4-6`

### 2. Fixed the Agentic Loop (Critical Bug)
- The original loop called one tool and returned immediately — it never sent the tool result back to the model
- Rewrote `run_agent()` as a proper while loop: invokes model → executes all tool calls → feeds `ToolMessage` results back → repeats until no more tool calls → returns final response

### 3. Added Multi-Turn Conversation Support
- `main.py`: added `history: list[dict] = []` field to `ChatRequest`
- `agent.py`: converts history dicts to `HumanMessage` / `AIMessage` objects before the loop
- Frontend now sends full conversation history with every request

### 4. Redesigned the Frontend UI
- Header with "✦ AI Agent / Claude Sonnet 4.6" badge
- Clear chat button (trash icon, only shown when messages exist)
- Message bubbles: indigo for user (right), white card for Claude (left)
- Avatars: gradient "✦" for Claude, "You" circle for user
- Timestamps below each bubble
- Three-dot bouncing typing indicator while loading
- Auto-growing textarea (max 160px), resets after send
- Empty state with centered prompt when no messages
- Removed Next.js footer promo

### 5. Created CLAUDE.md
- Full project documentation for future Claude Code sessions
- Covers stack, how to run, backend/frontend internals, migration history, known TODOs

### 6. Fixed .gitignore (Was Completely Broken)
- File had markdown code fences (` ``` `) wrapping it — none of the rules were active
- Rewrote as a proper gitignore
- Added `demoenv/` and `*env/` to cover the Python virtualenv

### 7. Fixed Nested Git Repo
- `frontend/.git` existed, making it a broken git submodule from the root repo's perspective
- Removed `frontend/.git` so frontend is tracked as regular files

### 8. Populated requirements.txt
- Was empty — froze all deps from `demoenv` with `pip freeze`

### 9. Made First Git Commit & Pushed to GitHub
- Remote: `git@github.com:asequitytrading-design/ai-agent-ui.git`
- Initial commit: `6604b74` — 22 files

### 10. Swapped Back to Groq (Temporary)
- Anthropic API not working during testing
- Reverted to `ChatGroq(model="openai/gpt-oss-120b")` — agentic loop and all other logic unchanged
- Commit: `ee7967f`

### 11. Implemented Real search_web Tool with SerpAPI
- Replaced dummy stub with `SerpAPIWrapper().run(query)` from `langchain_community`
- Installed `google-search-results==2.4.2` and updated `requirements.txt`
- Commit: `ef643f7`

---

## Current State of the Codebase

| Component | Status |
|-----------|--------|
| FastAPI backend (`main.py`) | ✅ Working — `/chat` endpoint with history support |
| Agentic loop (`agent.py`) | ✅ Fixed — proper multi-turn tool loop |
| LLM | ⚠️ Groq `openai/gpt-oss-120b` (temporary — Claude Sonnet 4.6 intended) |
| `get_current_time` tool | ✅ Working |
| `search_web` tool | ✅ Implemented with SerpAPI — needs `SERPAPI_API_KEY` env var |
| Frontend chat UI | ✅ Redesigned and working |
| Multi-turn history | ✅ Working |
| Git + GitHub | ✅ Clean — 3 commits pushed |

---

## What's Pending

### High Priority
- **Fix Anthropic API access** — once resolved, swap back to Claude:
  - `agent.py` line 1: `from langchain_anthropic import ChatAnthropic`
  - `agent.py` line 29: `llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)`
  - Update comment on line 28 to reflect Claude again
- **Set `SERPAPI_API_KEY`** — sign up at serpapi.com, get key, export before running backend

### Nice to Have
- **Streaming responses** — currently the backend waits for the full agentic loop before responding; SSE or WebSockets would make the UI feel faster
- **Move backend URL to env var** — `http://127.0.0.1:8181` is hardcoded in `frontend/app/page.tsx`; move to `.env.local` for easier deployment
- **Session persistence** — conversation history is lost on page refresh (stored only in React state)
- **Real search_web error handling** — SerpAPI calls can fail; wrap in try/except and return a graceful error message
- **Replace placeholder tools** — `search_web` now uses SerpAPI; could add more tools (calculator, weather, etc.)

---

## Environment Variables Required to Run

```bash
# Backend
export GROQ_API_KEY=...          # current (Groq)
export SERPAPI_API_KEY=...       # for search_web tool

# When switching back to Claude:
export ANTHROPIC_API_KEY=...     # replaces GROQ_API_KEY
```

## How to Run

```bash
# Backend
cd backend
source demoenv/bin/activate
uvicorn main:app --port 8181 --reload

# Frontend (separate terminal)
cd frontend
npm run dev
# → http://localhost:3000
```

## Git Log

| Commit | Message |
|--------|---------|
| `6604b74` | Initial commit: agentic chat app with Claude Sonnet 4.6 |
| `ee7967f` | chore: swap LLM back to Groq (openai/gpt-oss-120b) for testing |
| `ef643f7` | feat: implement search_web tool with SerpAPI (real Google results) |
