# CLAUDE.md — AI Agent UI

Project context for Claude Code. Read this before making any changes.

---

## What This Project Is

A fullstack agentic chat application:
- **Frontend**: Next.js 16 + React 19 + TypeScript + Tailwind CSS 4
- **Backend**: Python FastAPI + LangChain + Groq `openai/gpt-oss-120b` *(temporary — Claude Sonnet 4.6 is the intended LLM once Anthropic API access is fixed)*

The UI is a chat interface. The backend runs an agentic loop — the LLM can call tools (`get_current_time`, `search_web`) and keeps looping until it has a final answer before responding to the user.

---

## Project Structure

```
ai-agent-ui/
├── .gitignore             # Root gitignore (covers both frontend + backend)
├── CLAUDE.md              # This file — project context for Claude Code
├── PROGRESS.md            # Session log: what was done, what's pending
├── frontend/              # Next.js app
│   ├── .gitignore         # Next.js-specific ignores (.next/, node_modules/, etc.)
│   ├── app/
│   │   ├── page.tsx       # Main chat UI (the only page)
│   │   ├── layout.tsx     # Root layout
│   │   └── globals.css    # Tailwind global styles
│   ├── public/            # Static SVG assets
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── next.config.ts
│   ├── eslint.config.mjs
│   └── postcss.config.mjs
│
└── backend/               # FastAPI server
    ├── main.py            # HTTP server, /chat endpoint
    ├── agent.py           # LangChain agent + tool definitions
    ├── requirements.txt   # Frozen pip deps (from demoenv)
    └── demoenv/           # Python virtualenv — NOT committed (in .gitignore)
```

---

## How to Run

### Backend
```bash
cd backend
source demoenv/bin/activate

export GROQ_API_KEY=...          # current LLM
export SERPAPI_API_KEY=...       # required for search_web tool

uvicorn main:app --port 8181 --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:3000
```

The frontend hardcodes the backend URL as `http://127.0.0.1:8181` (move to `.env.local` before deploying).

---

## Backend Details

### `backend/main.py`
- FastAPI app with CORS open to all origins
- Single POST endpoint: `/chat`
- Request body:
  ```json
  { "message": "user text", "history": [{"role": "user"|"assistant", "content": "..."}] }
  ```
- Response: `{ "response": "assistant text" }`

### `backend/agent.py`
- **Current LLM**: `langchain_groq.ChatGroq(model="openai/gpt-oss-120b", temperature=0)` *(temporary)*
- **Intended LLM**: `langchain_anthropic.ChatAnthropic(model="claude-sonnet-4-6", temperature=0)`
- Tools bound via `llm.bind_tools(tools)`
- **Agentic loop**: keeps invoking the model, executes all tool calls, feeds `ToolMessage` results back, repeats until no more tool calls — then returns `response.content`
- History dicts are converted to `HumanMessage` / `AIMessage` objects before the loop
- Two tools:
  - `get_current_time()` — returns `datetime.datetime.now()`
  - `search_web(query: str)` — calls `SerpAPIWrapper().run(query)` (requires `SERPAPI_API_KEY`)

### Switching back to Claude (2-line change in `agent.py`)
```python
# Line 1 — change import
from langchain_anthropic import ChatAnthropic

# Line 29 — change model init
llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
```
Then update the comment on line 28 and set `ANTHROPIC_API_KEY` instead of `GROQ_API_KEY`.

---

## Frontend Details

### `frontend/app/page.tsx`
- Single-page chat UI, `"use client"` component
- State: `messages` (array of `{role, content, timestamp}`), `input`, `loading`
- On send: appends user message, POSTs to backend with full `history` array, appends assistant reply
- Multi-turn: every request sends the full prior conversation as `history`

**UI elements:**
- Header with "✦ AI Agent / Claude Sonnet 4.6" badge + clear chat button (trash icon, only shown when messages exist)
- Chat bubbles: indigo for user (right), white card for assistant (left)
- Avatars: gradient "✦" circle for assistant, "You" circle for user
- Timestamps below each bubble
- Three-dot bouncing typing indicator while loading
- Auto-growing textarea (max 160px), resets after send
- Enter to send, Shift+Enter for newline
- Empty state with centered prompt when no messages

---

## Git & GitHub

- **Remote**: `git@github.com:asequitytrading-design/ai-agent-ui.git`
- **Branch**: `main`

| Commit | Message |
|--------|---------|
| `6604b74` | Initial commit: agentic chat app with Claude Sonnet 4.6 |
| `ee7967f` | chore: swap LLM back to Groq (openai/gpt-oss-120b) for testing |
| `ef643f7` | feat: implement search_web tool with SerpAPI (real Google results) |

---

## Decisions Made

- **Virtualenv name is `demoenv`** — the root `.gitignore` covers it with `demoenv/` and `*env/`
- **`frontend/.git` was removed** — it was a nested git repo causing submodule issues; frontend is now tracked as regular files inside the root repo
- **SerpAPI chosen over Google Custom Search API** — simpler setup (one API key, no Google Cloud project), free tier is sufficient, already supported by `langchain-community`
- **`requirements.txt` is now frozen** — populated from `demoenv` with `pip freeze`; update it whenever new packages are installed

---

## Known Limitations / TODOs

- **Anthropic API not working** — currently on Groq as a workaround; switch back when resolved (see 2-line change above)
- **`SERPAPI_API_KEY` must be set** — `search_web` will throw without it; get key at serpapi.com (100 free searches/month)
- **No streaming** — backend waits for full agentic loop before responding; SSE or WebSockets would improve perceived speed
- **No session persistence** — history lives only in React state, lost on page refresh
- **Backend URL hardcoded** — `http://127.0.0.1:8181` in `page.tsx`; move to `frontend/.env.local` before deploying
- **No error handling on search_web** — SerpAPI calls can fail; should wrap in try/except
