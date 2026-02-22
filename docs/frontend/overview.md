# Frontend Overview

The frontend is a Next.js 16 application with a single page: a chat UI that communicates with the FastAPI backend. There is no routing, no global state management library, and no external UI component library — everything is built with React hooks and Tailwind CSS.

---

## File Structure

```
frontend/
├── app/
│   ├── page.tsx      # The entire chat UI — the only page
│   ├── layout.tsx    # Root layout (html + body tags, font setup)
│   └── globals.css   # Tailwind CSS imports + base styles
├── public/           # Static SVG assets (Next.js defaults)
├── package.json
├── tsconfig.json
├── next.config.ts
├── postcss.config.mjs
└── eslint.config.mjs
```

---

## Component Architecture

`page.tsx` exports a single `"use client"` component: `ChatPage`. It is self-contained — all state, event handlers, and rendering live in this one file.

### State

```typescript
interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

const [messages, setMessages] = useState<Message[]>([]);
const [input, setInput]       = useState("");
const [loading, setLoading]   = useState(false);
```

- `messages` — the full conversation history rendered as bubbles.
- `input` — the current value of the textarea.
- `loading` — `true` while a request is in flight; controls the typing indicator and disables the textarea.

### Refs

```typescript
const messagesEndRef = useRef<HTMLDivElement>(null);  // scroll target
const textareaRef    = useRef<HTMLTextAreaElement>(null);  // height + focus
```

### Effects

```typescript
useEffect(() => {
  messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
}, [messages, loading]);
```

Auto-scrolls to the bottom of the message list whenever messages change or loading state toggles (to keep the typing indicator in view).

---

## Message Send Flow

```
User presses Enter (or clicks send button)
         │
         ▼
sendMessage()
  1. Return early if input is empty or loading
  2. Create userMessage: Message
  3. setMessages([...messages, userMessage])   ← optimistic UI update
  4. setInput("")                              ← clear textarea
  5. setLoading(true)                          ← show typing indicator
  6. Reset textarea height to "auto"
  7. axios.post("http://127.0.0.1:8181/chat", {
       message: userMessage.content,
       history: messages.map(m => ({ role: m.role, content: m.content }))
     })
  8a. Success:
       Create assistantMessage from res.data.response
       setMessages([...updated, assistantMessage])
  8b. Error (network, timeout, 4xx, 5xx):
       Create assistantMessage: "Error connecting to server. Is the backend running?"
       setMessages([...updated, assistantMessage])
  9. setLoading(false)
```

### History Construction

The frontend sends the **full conversation history** with every request. The history is derived from the current `messages` state, excluding the timestamp field:

```typescript
history: messages.map(m => ({ role: m.role, content: m.content }))
```

Note that `messages` at the time of the POST already includes the new user message (appended in step 3), but the POST body separates it into `message` (the latest input) and `history` (everything before it). The backend never receives timestamps.

### Multi-Turn Context

Because the full history is sent on every request, the LLM on the backend sees the complete conversation context and can answer follow-up questions:

| Turn | `message` sent | `history` sent |
|------|----------------|----------------|
| 1 | `"Hello"` | `[]` |
| 2 | `"What time is it?"` | `[{user: "Hello"}, {assistant: "Hi!"}]` |
| 3 | `"Was that AM or PM?"` | `[{user: "Hello"}, {assistant: "Hi!"}, {user: "What time is it?"}, {assistant: "2:37 PM"}]` |

!!! warning "No persistence"
    History is stored only in React component state. Refreshing the page clears the entire conversation.

---

## UI Layout

```
┌────────────────────────────────────────────┐
│  ✦ AI Agent  [badge: Claude Sonnet 4.6]  🗑 │  ← header (trash icon only if messages exist)
├────────────────────────────────────────────┤
│                                            │
│  [empty state: ✦ icon + prompt text]       │  ← shown when messages = []
│                                            │
│  ✦  ┌──────────────────────────────┐       │  ← assistant bubble (left)
│     │ Assistant reply text         │       │
│     └──────────────────────────────┘       │
│     2:37 PM                                │
│                                            │
│              ┌──────────────────────┐  You │  ← user bubble (right)
│              │ User message text    │      │
│              └──────────────────────┘      │
│                                     2:37 PM│
│                                            │
│  ✦  ┌──────────────┐                       │  ← typing indicator (while loading)
│     │ ◦  ◦  ◦      │                       │
│     └──────────────┘                       │
├────────────────────────────────────────────┤
│  ┌────────────────────────────────────┐ [▶]│  ← input area
│  │  textarea (auto-grow, max 160px)   │    │
│  └────────────────────────────────────┘    │
│  Shift+Enter for new line · Enter to send  │
└────────────────────────────────────────────┘
```

### Styling Details

| Element | Classes |
|---------|---------|
| User bubble | `bg-indigo-600 text-white rounded-br-sm` (right-aligned) |
| Assistant bubble | `bg-white border border-gray-100 rounded-bl-sm` (left-aligned) |
| Assistant avatar | Gradient circle with `✦` character |
| User avatar | Solid circle with "You" text |
| Timestamp | `text-[11px] text-gray-400` |
| Typing dots | Three `div` elements with staggered `animate-bounce` |
| Textarea | Auto-grows on `input` event; capped at `160px` via JS |

---

## Keyboard Behaviour

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Shift+Enter` | Insert newline in textarea |

Implemented in `handleKeyDown()`:

```typescript
if (e.key === "Enter" && !e.shiftKey) {
  e.preventDefault();
  sendMessage();
}
```

---

## Dependencies

Key packages from `package.json`:

| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 16.x | Framework |
| `react` | 19.x | UI library |
| `axios` | latest | HTTP client |
| `typescript` | 5.x | Type checking |
| `tailwindcss` | 4.x | Utility CSS |

---

## Known Limitations

- **Backend URL hardcoded** — `http://127.0.0.1:8181` is inline in `sendMessage()`. Move to `NEXT_PUBLIC_BACKEND_URL` in `frontend/.env.local` before deploying.
- **No request timeout** — axios has no timeout set; a hung backend will block the UI until the browser times out (~5 minutes).
- **No streaming** — the response appears all at once after the full agentic loop completes. SSE or WebSockets would allow progressive rendering.
- **No session persistence** — conversation history is lost on page refresh.
- **`agent_id` not exposed in the UI** — the frontend always uses the backend's default (`"general"`). A future UI could let users select an agent from the `GET /agents` endpoint.
