# SSR Hydration Mismatches in Next.js App Router

## Problem
`"use client"` components still run on the server for SSR. If they produce different HTML on server vs client, React throws a hydration error and regenerates the entire tree.

## Common Causes

### 1. crypto.randomUUID() in useState
```typescript
// BAD — different UUID on server vs client
const [id] = useState(() => crypto.randomUUID());

// GOOD — generate only on client via useRef
const ref = useRef("");
if (typeof window !== "undefined" && !ref.current) {
  ref.current = crypto.randomUUID();
}
```

### 2. localStorage reads during render
```typescript
// BAD — localStorage doesn't exist on server
const [theme] = useState(localStorage.getItem("theme"));

// GOOD — initialize with default, hydrate in useEffect
const [theme, setTheme] = useState("system");
useEffect(() => setTheme(localStorage.getItem("theme") ?? "system"), []);
```

### 3. SVG filter elements
SVG `<filter>`, `<defs>`, and `<linearGradient>` elements can render differently between server and client. Wrap chart components with a mounted guard.

### 4. Context providers with browser APIs
WebSocket connections, localStorage reads in providers cause mismatches.

## Nuclear Fix: Mounted Guard on Layout
For auth-gated layouts where everything needs browser APIs:
```typescript
const [mounted, setMounted] = useState(false);
useEffect(() => setMounted(true), []);
if (!mounted) return <Spinner />;
return <LayoutProvider><ChatProvider>...</ChatProvider></LayoutProvider>;
```
This shows a brief spinner on first render but eliminates all hydration mismatches.

## When to Use
- Auth-gated routes with JWT/localStorage
- Pages with WebSocket connections
- Charts with SVG filters (react-plotly.js, custom SVG)
- Any component reading `window`, `document`, `localStorage` during render
