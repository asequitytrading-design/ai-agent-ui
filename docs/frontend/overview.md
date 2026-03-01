# Frontend Overview

The frontend is a Next.js 16 application with a single `page.tsx` component that implements a full SPA: a chat UI, an embedded Docs viewer, and an embedded Dashboard viewer — all within one mounted React component.  In addition to the classic email / password flow, the app now supports Google + Facebook SSO via OAuth2 PKCE.

---

## File Structure

```
frontend/
├── app/
│   ├── page.tsx                               # SPA shell — composes hooks + components
│   ├── login/
│   │   └── page.tsx                           # Login page — email + password **and** SSO buttons
│   ├── auth/
│   │   └── oauth/
│   │       └── callback/
│   │           └── page.tsx                 # OAuth callback – exchanges code for JWTs
│   ├── layout.tsx                             # Root layout (html + body tags, font setup)
│   └── globals.css                            # Tailwind CSS imports + base styles
├── components/                                # Extracted UI components
│   ├── ChatHeader.tsx                         # Header bar + agent selector + profile dropdown
│   ├── ChatInput.tsx                          # Textarea + send button
│   ├── MessageBubble.tsx                      # Individual message bubble (with MarkdownContent)
│   ├── MarkdownContent.tsx                    # Memoised markdown renderer
│   ├── NavigationMenu.tsx                     # FAB + popup nav (RBAC-filtered by profile)
│   ├── IFrameView.tsx                         # Dashboard/Docs iframe wrapper
│   ├── StatusBadge.tsx                        # Animated thinking/streaming badge
│   ├── EditProfileModal.tsx                   # Avatar upload + full_name edit modal
│   └── ChangePasswordModal.tsx               # Password reset modal
├── hooks/                                     # Custom React hooks
│   ├── useAuthGuard.ts                        # Redirect to /login if no valid token
│   ├── useChatHistory.ts                      # Per-agent history + debounced localStorage save
│   ├── useSendMessage.ts                      # Streaming fetch with AbortController
│   ├── useEditProfile.ts                      # PATCH /auth/me + avatar upload
│   └── useChangePassword.ts                   # Password-reset two-step flow
├── lib/
│   ├── auth.ts                                # JWT token helpers (getAccessToken, setTokens, …)
│   ├── oauth.ts                               # PKCE helpers + sessionStorage helpers for SSO
│   ├── apiFetch.ts                            # Authenticated fetch wrapper (auto‑refresh + 401 redirect)
│   └── constants.ts                           # AGENTS list, NAV_ITEMS, View type
├── public/                                    # Static SVG assets (Next.js defaults)
├── .env.local                                 # Runtime env vars (gitignored)
├── .env.local.example                         # Committed reference copy
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

All three are used at runtime in the browser (they're embedded in the client bundle by Next.js). Fallback values are hard‑coded in the component for zero‑config local dev.

---

## Component Architecture

`page.tsx` exports a single `"use client"` component: `ChatPage`. State and logic are split across custom hooks in `hooks/`; rendering is delegated to components in `components/`. `page.tsx` acts as a slim composition shell.

### Types (`lib/constants.ts`)

```typescript
type View = "chat" | "docs" | "dashboard" | "admin" | "insights";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}
```

### State (in `page.tsx`)

| State | Type | Purpose |
|-------|------|---------|
| `view` | `View` | Which surface is rendered |
| `iframeUrl` | `string \| null` | Specific URL for the iframe (e.g. `/analysis?ticker=AAPL`); `null` = base URL |
| `iframeLoading` | `boolean` | `true` while the iframe is loading; shows spinner overlay |
| `iframeError` | `boolean` | `true` if the iframe `onError` fires; shows error banner |
| `agentId` | `string` | Active agent (`"general"` or `"stock"`) |
| `input` | `string` | Current textarea value |
| `loading` | `boolean` | `true` while a backend request is in flight |
| `statusLine` | `string` | Human‑readable status text shown in `StatusBadge` during streaming |
| `menuOpen` | `boolean` | Navigation menu open/closed |
| `profile` | `UserProfile \| null` | Fetched from `GET /auth/me`; drives profile dropdown + RBAC |

### Hook responsibilities

| Hook | State owned |
|------|-------------|
| `useAuthGuard` | Redirect to `/login` if no valid token |
| `useChatHistory(agentId)` | Per-agent `messages` array; debounced localStorage save |
| `useSendMessage(...)` | `sendMessage`, `handleKeyDown`, `handleInput`; AbortController cleanup |
| `useEditProfile()` | `isOpen`, `saving`, `error`; `PATCH /auth/me` + avatar upload |
| `useChangePassword()` | `isOpen`, `saving`, `error`; password-reset two-step flow |

### Refs

```typescript
const messagesEndRef = useRef<HTMLDivElement>(null);   // auto‑scroll anchor
const textareaRef    = useRef<HTMLTextAreaElement>(null); // height + focus
const menuRef        = useRef<HTMLDivElement>(null);   // click‑outside detection
```

### Effects (in `page.tsx`)

```typescript
// Profile fetch on mount — AbortController cancels if unmounted
useEffect(() => {
  const controller = new AbortController();
  apiFetch(`${BACKEND_URL}/auth/me`, { signal: controller.signal })
    .then(res => res.ok ? res.json() : null)
    .then(data => { if (data) setProfile(data); })
    .catch(err => { if (err?.name !== "AbortError") { /* ignore */ } });
  return () => controller.abort();
}, []);

// Auto‑scroll to latest message
useEffect(() => {
  messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
}, [messages, loading]);

// Stable click‑outside handler (useCallback) to close navigation menu
useEffect(() => {
  if (!menuOpen) return;
  document.addEventListener("mousedown", handleMenuOutsideClick);
  return () => document.removeEventListener("mousedown", handleMenuOutsideClick);
}, [menuOpen, handleMenuOutsideClick]);
```

**localStorage save** is debounced 1 second inside `useChatHistory` to avoid blocking the main thread on every streaming token.

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
  setIframeUrl(null);        // reset to base URL; menu always opens homepage
  setMenuOpen(false);
  if (v !== "chat") {
    setIframeLoading(true);  // show spinner until onLoad fires
    setIframeError(false);
  }
};
```

### handleInternalLink

When the LLM produces a link pointing to the dashboard or docs (see [Path Replacement](#path-replacement)), clicking it calls:

```typescript
const handleInternalLink = (href: string) => {
  if (href.startsWith(dashboardBase)) {
    setView("dashboard");
    setIframeUrl(href);        // e.g. http://127.0.0.1:8050/analysis?ticker=AAPL
    setIframeLoading(true);
    setIframeError(false);
  } else if (href.startsWith(docsBase)) {
    setView("docs");
    setIframeUrl(href);
    setIframeLoading(true);
    setIframeError(false);
  }
};
```

The iframe then loads that exact URL inside the app window.

### Iframe loading and error states

The `<iframe>` element has `onLoad` and `onError` handlers:

- `onLoad` — sets `iframeLoading = false`, removing the spinner overlay.
- `onError` — sets `iframeLoading = false` and `iframeError = true`, showing an error banner with an "Open in new tab ↗" link.

The `<iframe>` also carries a `sandbox` attribute permitting scripts, same‑origin access, forms, and popups, and `referrerPolicy="no-referrer"`. An "Open in new tab ↗" button is always visible in the header when `view !== "chat"` — not just on error.

---

## Authentication

### Auth guard

On every mount, `page.tsx` checks for a valid, unexpired access token. If none exists, the user is redirected to `/login` immediately. A loading spinner is shown until the guard resolves, preventing a flash of the chat UI.

### Login page (SSO support)

`frontend/app/login/page.tsx` now renders:

* The classic email / password form.
* **SSO buttons** for Google and Facebook when the corresponding provider is enabled (fetched from `GET /auth/oauth/providers`).
* Clicking a button triggers the PKCE flow defined in `frontend/lib/oauth.ts`:
  1. Generate a random `code_verifier` and its `code_challenge`.
  2. Call `GET /auth/oauth/{provider}/authorize?code_challenge=…` to obtain a consent URL and a one‑time `state` value.
  3. Store `state`, `code_verifier`, and `provider` in `sessionStorage`.
  4. Redirect the browser to the provider's consent page.
* After the provider redirects back to `/auth/oauth/callback`, the callback page exchanges the `code` (and, for Google, the stored verifier) for a JWT pair, stores them via `setTokens()`, and redirects to the main chat view.

### Header controls

When `view === "chat"`, the header shows:

- **Agent selector** — toggle between General and Stock Analysis
- **Logout button** — calls `clearTokens()` + `router.replace("/login")`
- **Clear button** — clears the active agent's chat history (only shown when messages exist)

### Admin nav item

The navigation menu includes an **Admin** item visible only to superusers. The role is decoded from the stored JWT with `getRoleFromToken()` — no extra API call required.

Clicking Admin sets `view = "admin"` and loads `DASHBOARD_URL/admin/users?token=<jwt>` in the iframe.

### Token propagation to iframes

When rendering a dashboard or admin iframe, the current access token is appended as a query parameter. The value is memoised (only recomputed when `view` or `iframeUrl` change) to avoid calling `getAccessToken()` on every render:

```typescript
const iframeSrc = useMemo(() => {
  const base = iframeUrl ?? defaultUrl;
  const token = getAccessToken();
  if (!token) return base;
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}token=${encodeURIComponent(token)}`;
}, [view, iframeUrl]);
```

The Dash app receives the token via `?token=`, stores it in `dcc.Store`, and validates it on every page render. Docs iframes do not require a token.

---

## Navigation Menu

A fixed‑position FAB button sits at `bottom-6 right-6` (rendered by `NavigationMenu`). Items are filtered by RBAC: Admin is only shown for superusers or users with the `admin` page permission; Insights requires superuser or `insights` page permission. Clicking it toggles a popup with visible items:

| Item | Icon | Action |
|------|------|--------|
| Chat | Message bubble | `switchView("chat")` |
| Docs | File icon | `switchView("docs")` — loads MkDocs |
| Dashboard | Grid icon | `switchView("dashboard")` — loads Dash |
| Admin | Shield icon | `switchView("admin")` — loads `/admin/users` (superusers only) |

The active view is highlighted with an indigo background and a small dot indicator. The menu closes when an item is clicked or when the user clicks outside.

---

## Message Send Flow

```
User presses Enter (or clicks send)
        │
        ▼
sendMessage()
  1. Guard: return if input empty or loading
  2. …
```

*(The rest of the flow remains unchanged.)*
