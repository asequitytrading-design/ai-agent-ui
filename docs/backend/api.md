# API Reference

The backend exposes two HTTP endpoints. Both are defined in `backend/main.py` and registered as bound methods of `ChatServer`.

Base URL (development): `http://127.0.0.1:8181`

---

## POST /chat

Send a message to an agent and receive a response.

### Request

```http
POST /chat
Content-Type: application/json
```

```json
{
  "message": "What time is it?",
  "history": [
    { "role": "user",      "content": "Hello" },
    { "role": "assistant", "content": "Hi! How can I help?" }
  ],
  "agent_id": "general"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `message` | `string` | Yes | — | The user's latest message |
| `history` | `array` | No | `[]` | Prior conversation turns, oldest first |
| `agent_id` | `string` | No | `"general"` | ID of the agent to handle the request |

Each `history` item must have:

| Field | Type | Values |
|-------|------|--------|
| `role` | `string` | `"user"` or `"assistant"` |
| `content` | `string` | The message text |

Any history entry with a role other than `"user"` or `"assistant"` is silently ignored.

### Response — 200 OK

```json
{
  "response": "The current time is 2026-02-22 14:37:55.",
  "agent_id": "general"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `response` | `string` | The agent's natural-language reply |
| `agent_id` | `string` | Echoed from the request |

### Response — 404 Not Found

Returned when the requested `agent_id` is not registered.

```json
{
  "detail": "Agent 'unknown' not found"
}
```

### Response — 500 Internal Server Error

Returned when an unhandled exception occurs inside the agentic loop.

```json
{
  "detail": "Agent execution failed"
}
```

!!! note
    In all error cases the backend returns a proper `HTTPException`. Error details are never embedded in a `200` response body.

---

## GET /agents

List all registered agents.

### Request

```http
GET /agents
```

No request body or parameters.

### Response — 200 OK

```json
{
  "agents": [
    {
      "id": "general",
      "name": "General Agent",
      "description": "A general-purpose agent that can answer questions and search the web."
    }
  ]
}
```

Each agent object contains:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Agent ID used in `POST /chat` `agent_id` field |
| `name` | `string` | Human-readable display name |
| `description` | `string` | One-sentence description of the agent's purpose |

---

## CORS

CORS is configured to allow all origins (`*`), all methods, and all headers. This is intentional for local development. Tighten the `allow_origins` list before deploying to production.

---

## Multi-Turn Conversations

The backend is stateless — it does not store conversation history between requests. The frontend is responsible for accumulating messages and sending the full `history` array with every request.

**Turn 1** — no history:
```json
{ "message": "Hello", "history": [] }
```

**Turn 2** — history includes Turn 1:
```json
{
  "message": "What time is it?",
  "history": [
    { "role": "user",      "content": "Hello" },
    { "role": "assistant", "content": "Hi! How can I help?" }
  ]
}
```

The backend converts each history entry to a LangChain `HumanMessage` or `AIMessage` and prepends them to the message array before invoking the LLM, giving the model full conversational context.

---

## Testing the API

Using curl:

```bash
# POST /chat
curl -s -X POST http://127.0.0.1:8181/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What time is it?", "history": []}' | python3 -m json.tool

# GET /agents
curl -s http://127.0.0.1:8181/agents | python3 -m json.tool
```

FastAPI also generates interactive docs automatically:

- **Swagger UI**: [http://127.0.0.1:8181/docs](http://127.0.0.1:8181/docs)
- **ReDoc**: [http://127.0.0.1:8181/redoc](http://127.0.0.1:8181/redoc)
