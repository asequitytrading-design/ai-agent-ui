# Frontend Overview

The frontend is a Next.js 16 application with a single `page.tsx` component that implements a full SPA: a chat UI, an embedded Docs viewer, and an embedded Dashboard viewer — all within one mounted React component.

---

## File Structure

```
frontend/
├── app/
│   ├── page.tsx              # Entire SPA — chat, docs, dashboard views
│   ├── layout.tsx            # Root layout (html + body tags, font setup)
│   └── globals.css           # Tailwind CSS imports + base styles
├── public/                   # Static SVG assets (Next.js defaults)
├── .env.local                # Runtime env vars (gitignored)
├── .env.local.example        # Committed reference copy
├── package.json
├── tsconfig.json
├── next.config.ts
├── postcss.config.mjs
└── eslint.config.mjs
```

### Environment Variables

`frontend/.env.local` (gitignored; copy from `.env.local.example`):

```
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8181
NEXT_PUBLIC_DASHBOARD_URL=http://127.0.0.1:8050
NEXT_PUBLIC_DOCS_URL=http://127.0.0.1:8000
```

All three are used at runtime in the browser (they're embedded in the client bundle by Next.js). Fallback values are hard-coded in the component for zero-config local dev.

---

## Component Architecture

`page.tsx` exports a single `"use client"` component: `ChatPage`. All state, handlers, and rendering live in this one file.

### Types

```typescript
type View = "chat" | "docs" | "dashboard";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}
```

### State

| State | Type | Purpose |
|-------|------|---------|
| `view` | `View` | Which surface is rendered |
| `iframeUrl` | `string \| null` | Specific URL for the iframe (e.g. `/analysis?ticker=AAPL`); `null` = base URL |
| `histories` | `Record<string, Message[]>` | Per-agent chat history, keyed by `agentId` |
| `input` | `string` | Current textarea value |
| `loading` | `boolean` | `true` while a backend request is in flight |
| `agentId` | `string` | Active agent (`"general"` or `"stock"`) |
| `menuOpen` | `boolean` | Navigation menu open/closed |

### Refs

```typescript
const messagesEndRef = useRef<HTMLDivElement>(null);   // auto-scroll anchor
const textareaRef    = useRef<HTMLTextAreaElement>(null); // height + focus
const menuRef        = useRef<HTMLDivElement>(null);   // click-outside detection
```

### Effects

```typescript
// Auto-scroll to latest message
useEffect(() => {
  messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
}, [messages, loading]);

// Load histories from localStorage on mount (revives Date objects)
useEffect(() => {
  const saved = localStorage.getItem("chat_histories");
  if (saved) { /* JSON.parse + new Date(m.timestamp) revival */ }
}, []);

// Save histories whenever they change
useEffect(() => {
  localStorage.setItem("chat_histories", JSON.stringify(histories));
}, [histories]);

// Click-outside handler to close navigation menu
useEffect(() => {
  if (!menuOpen) return;
  document.addEventListener("mousedown", handleClick);
  return () => document.removeEventListener("mousedown", handleClick);
}, [menuOpen]);
```

---

## View Routing

The `view` state controls which surface fills the space below the header.

```
view === "chat"
  → <main> (scrollable chat messages) + <footer> (input area)

view === "docs" | "dashboard"
  → <iframe src={iframeUrl ?? baseServiceUrl} className="flex-1 w-full border-0" />
```

Switching views **does not unmount the component**, so `histories`, `input`, and all other React state is preserved when the user navigates away from chat and back.

### switchView

```typescript
const switchView = (v: View) => {
  setView(v);
  setIframeUrl(null);   // reset to base URL; menu always opens homepage
  setMenuOpen(false);
};
```

### handleInternalLink

When the LLM produces a link pointing to the dashboard or docs (see [Path Replacement](#path-replacement)), clicking it calls:

```typescript
const handleInternalLink = (href: string) => {
  if (href.startsWith(dashboardBase)) {
    setView("dashboard");
    setIframeUrl(href);   // e.g. http://127.0.0.1:8050/analysis?ticker=AAPL
  } else if (href.startsWith(docsBase)) {
    setView("docs");
    setIframeUrl(href);
  }
};
```

The iframe then loads that exact URL inside the app window.

---

## Navigation Menu

A fixed-position FAB button sits at `bottom-6 right-6`. Clicking it toggles a popup with three items:

| Item | Icon | Action |
|------|------|--------|
| Chat | Message bubble | `switchView("chat")` |
| Docs | File icon | `switchView("docs")` — loads MkDocs |
| Dashboard | Grid icon | `switchView("dashboard")` — loads Dash |

The active view is highlighted with an indigo background and a small dot indicator. The menu closes when an item is clicked or when the user clicks outside.

---

## Message Send Flow

```
User presses Enter (or clicks send)
        │
        ▼
sendMessage()
  1. Guard: return if input empty or loading
  2. Create userMessage: Message (timestamp = new Date())
  3. setMessages([...messages, userMessage])   ← optimistic update
  4. setInput("") + reset textarea height
  5. setLoading(true)
  6. POST ${NEXT_PUBLIC_BACKEND_URL}/chat
       { message, history: messages (role+content only), agent_id }
  7a. Success → append assistantMessage from res.data.response
  7b. Error   → append "Error connecting to server..." message
  8. setLoading(false) + focus textarea
```

---

## Path Replacement

The `preprocessContent(content)` function runs before `ReactMarkdown` renders each assistant message:

| Input pattern | Replacement |
|---------------|-------------|
| `*/charts/analysis/{TICKER}_analysis.html` | `[View {TICKER} Analysis →](DASHBOARD_URL/analysis?ticker={TICKER})` |
| `*/charts/forecasts/{TICKER}_forecast.html` | `[View {TICKER} Forecast →](DASHBOARD_URL/forecast?ticker={TICKER})` |
| `*/data/(raw\|processed\|forecasts\|cache\|metadata)/*` | *(removed entirely)* |

The generated links are rendered by the custom `a` component in `MarkdownContent`. If the `href` starts with `NEXT_PUBLIC_DASHBOARD_URL` or `NEXT_PUBLIC_DOCS_URL`, a `<button>` calling `onInternalLink` is rendered instead of `<a target="_blank">`. External links still open in a new tab.

---

## Session Persistence

Chat history survives page refreshes via `localStorage`:

- **Key**: `"chat_histories"`
- **Value**: JSON-serialised `Record<string, Message[]>` — `Date` objects serialise as ISO strings
- **Revival**: on mount, `new Date(m.timestamp)` converts the ISO string back to a `Date` so `formatTime()` works correctly
- **Clear**: the "Clear" button calls `setMessages([])` which triggers the save effect and overwrites localStorage with the cleared state

---

## UI Layout

```
┌────────────────────────────────────────────────────────┐
│  ✦ AI Agent  [General | Stock Analysis]           [🗑]  │  ← header
│           (breadcrumb label when view ≠ chat)          │
├────────────────────────────────────────────────────────┤
│                                                        │
│  [chat view: message bubbles + empty state]            │
│  ── OR ──                                              │
│  [iframe filling remaining height]                     │
│                                                        │
├────────────────────────────────────────────────────────┤
│  [input area — chat view only]                         │
│  ┌──────────────────────────────────┐ [▶]              │
│  │  textarea                        │                  │
│  └──────────────────────────────────┘                  │
│  Shift+Enter for new line · Enter to send              │
└────────────────────────────────────────────────────────┘
                                             [⊞] ← FAB (bottom-right)
```

---

## Keyboard Behaviour

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Shift+Enter` | Insert newline |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 16.x | Framework |
| `react` | 19.x | UI library |
| `axios` | latest | HTTP client |
| `react-markdown` | 10.x | Markdown rendering for assistant replies |
| `remark-gfm` | 4.x | Tables, strikethrough, task lists |
| `typescript` | 5.x | Type checking |
| `tailwindcss` | 4.x | Utility CSS |

---

## Known Limitations

- **No request timeout** — axios has no timeout set; a hung backend blocks the UI until the browser times out.
- **No streaming** — the full response appears at once after the agentic loop completes.
- **iframe cross-origin limits** — `localStorage`, cookie sharing, and deep linking into MkDocs/Dash pages work; JavaScript calls across iframe boundaries do not (and are not needed).
