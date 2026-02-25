# Authentication & User Management

The auth module adds JWT-based authentication and role-based access control (RBAC) to all three surfaces: the **chat frontend** (Next.js), the **dashboard** (Plotly Dash), and the **FastAPI backend**.

Storage is Apache Iceberg via PyIceberg with a SQLite-backed SqlCatalog — no extra database server required.

---

## Quick Start

```bash
# 1. Generate a strong secret key
python -c "import secrets; print(secrets.token_hex(32))"

# 2. Add required env vars to .env at the project root
cat >> .env <<EOF
JWT_SECRET_KEY=<paste-output-above>
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=Admin1234
ADMIN_FULL_NAME=Admin User
EOF

# 3. Initialise Iceberg tables (one-time, idempotent)
python auth/create_tables.py

# 4. Seed the first superuser
python scripts/seed_admin.py

# 5. Start everything
./run.sh start
# → log in at http://localhost:3000/login
```

!!! note "Automatic init on `./run.sh start`"
    Steps 3 and 4 run automatically the first time you call `./run.sh start`,
    provided `JWT_SECRET_KEY`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD` are set.

---

## Architecture

```
auth/
├── __init__.py          Package init
├── create_tables.py     One-time Iceberg table setup (idempotent)
├── repository.py        IcebergUserRepository — CRUD + audit log
├── service.py           AuthService — bcrypt + JWT lifecycle
├── models.py            Pydantic request/response models
├── dependencies.py      FastAPI dependency functions
└── api.py               create_auth_router() — all endpoints

scripts/
└── seed_admin.py        Bootstrap first superuser from env vars
```

### Storage — Apache Iceberg

Two Iceberg tables backed by a SQLite catalog at `data/iceberg/catalog.db`.

| Table | Namespace | Purpose |
|---|---|---|
| `auth.users` | `auth` | User accounts and credentials |
| `auth.audit_log` | `auth` | Immutable event history |

The warehouse lives at `data/iceberg/warehouse/` and is gitignored.  The catalog config is read from `.pyiceberg.yaml` in the project root (gitignored; copy from `.pyiceberg.yaml.example`).

### Password hashing — bcrypt

`AuthService` uses `passlib[bcrypt]` with cost factor 12 (~250 ms per hash on a modern CPU).  Only the hash is stored; plaintext passwords never appear in logs.

### JWT tokens — HS256

| Token | Payload fields | TTL |
|---|---|---|
| Access | `sub`, `email`, `role`, `type="access"`, `jti`, `iat`, `exp` | 60 min (configurable) |
| Refresh | `sub`, `type="refresh"`, `jti`, `iat`, `exp` | 7 days (configurable) |

Refresh tokens are rotated on every `/auth/refresh` call — the old token is immediately revoked.  Logout adds the JTI to an in-memory deny-list (cleared on restart; acceptable for single-server MVP).

### Roles

| Role | Permissions |
|---|---|
| `superuser` | Full access: all user CRUD + audit log |
| `general` | Chat and dashboard only; cannot access `/users` or `/admin/*` |

---

## API Endpoints

Base URL: `http://127.0.0.1:8181`

### Auth

#### `POST /auth/login`

Authenticate with email + password.  Returns a JWT access + refresh token pair.

```http
POST /auth/login
Content-Type: application/json
```

```json
{ "email": "admin@example.com", "password": "Admin1234" }
```

**Response 200:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

**Error codes:** `401` invalid credentials / deactivated account.

---

#### `POST /auth/login/form`

OAuth2 form-based login (used by the OpenAPI "Authorize" button at `/docs`).  Accepts `application/x-www-form-urlencoded` with `username` (email) and `password`.

---

#### `POST /auth/refresh`

Exchange a valid refresh token for a new access + refresh token pair.  The old refresh token is revoked immediately.

```json
{ "refresh_token": "eyJ..." }
```

**Error codes:** `401` expired / revoked / invalid token.

---

#### `POST /auth/logout`

Revoke the supplied refresh token.

```http
Authorization: Bearer <access_token>
```
```json
{ "refresh_token": "eyJ..." }
```

---

#### `POST /auth/password-reset/request`

Generate a single-use 30-minute password reset token for the authenticated user.  The caller may only reset their own password.

```http
Authorization: Bearer <access_token>
```
```json
{ "email": "admin@example.com" }
```

!!! warning "Development mode"
    The reset token is returned in the response body for development.
    In production, replace this with email delivery and omit the token from the response.

---

#### `POST /auth/password-reset/confirm`

Apply a new password using the reset token from the previous step.  The token is single-use.

```http
Authorization: Bearer <access_token>
```
```json
{ "reset_token": "<uuid>", "new_password": "NewPass1" }
```

**Error codes:** `400` invalid/expired token or password too weak.

---

### Users (superuser only)

All user management endpoints require a superuser access token:

```http
Authorization: Bearer <superuser_access_token>
```

#### `GET /users`

List all user accounts.

**Response 200:** array of `UserResponse` objects.

---

#### `POST /users`

Create a new user account.

```json
{
  "email": "jane@example.com",
  "password": "Jane1234",
  "full_name": "Jane Doe",
  "role": "general"
}
```

**Error codes:** `400` password too weak, `409` email already in use.

---

#### `GET /users/{user_id}`

Get a single user by UUID.

**Error codes:** `404` user not found.

---

#### `PATCH /users/{user_id}`

Update a user's details.  All fields are optional; only supplied fields are changed.

```json
{
  "full_name": "Jane Smith",
  "email": "jsmith@example.com",
  "role": "superuser",
  "is_active": false
}
```

**Error codes:** `404` user not found, `409` email already in use.

---

#### `DELETE /users/{user_id}`

Soft-delete a user (`is_active = false`).  Superusers cannot delete themselves.

**Error codes:** `400` self-delete attempted, `404` user not found.

---

### Admin (superuser only)

#### `GET /admin/audit-log`

Return all audit log events, sorted newest-first.

**Response 200:**
```json
{
  "events": [
    {
      "event_id": "...",
      "event_type": "LOGIN",
      "actor_user_id": "...",
      "target_user_id": "...",
      "event_timestamp": "2026-02-25T10:00:00",
      "metadata": "{\"stage\": \"confirm\"}"
    }
  ]
}
```

**Event types:** `USER_CREATED`, `USER_UPDATED`, `USER_DELETED`, `LOGIN`, `PASSWORD_RESET`.

---

## Pydantic Models

Defined in `auth/models.py`:

| Model | Used by |
|---|---|
| `LoginRequest` | `POST /auth/login` body |
| `TokenResponse` | All token-returning endpoints |
| `RefreshRequest` | `POST /auth/refresh` body |
| `LogoutRequest` | `POST /auth/logout` body |
| `PasswordResetRequestBody` | `POST /auth/password-reset/request` body |
| `PasswordResetConfirmBody` | `POST /auth/password-reset/confirm` body |
| `UserCreateRequest` | `POST /users` body |
| `UserUpdateRequest` | `PATCH /users/{id}` body |
| `UserContext` | Injected into routes by `get_current_user` dependency |
| `UserResponse` | All user-returning endpoints (no sensitive fields) |

---

## FastAPI Dependencies

Defined in `auth/dependencies.py`:

```python
# Require a valid access token; returns UserContext
get_current_user: Depends(oauth2_scheme) → UserContext

# Require superuser role; raises HTTP 403 otherwise
superuser_only: Depends(get_current_user) → UserContext

# Return the AuthService singleton (lru_cache)
get_auth_service: Callable → AuthService
```

---

## Configuration

Add these to `backend/.env` (or export as environment variables):

```bash
# Required
JWT_SECRET_KEY=<min-32-random-chars>

# Optional (shown with defaults)
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
```

`backend/config.py` `Settings` reads all three fields automatically.

---

## Frontend Login Flow

### File structure

```
frontend/
├── app/
│   ├── login/
│   │   └── page.tsx      # Login page — email + password form
│   └── page.tsx          # Main SPA — auth guard + logout + Admin nav item
└── lib/
    ├── auth.ts            # Token helpers (localStorage ↔ JWT)
    └── apiFetch.ts        # Authenticated fetch wrapper (auto-refresh)
```

### Login page — `frontend/app/login/page.tsx`

Renders a centered email + password form.

- On mount: if a **valid, unexpired** access token already exists, redirects immediately to `/` (covers browser back-button scenarios).
- On submit: calls `POST /auth/login` with `{ email, password }`.
  - **Success** → calls `setTokens(access, refresh)` and redirects to `/`.
  - **Failure** → shows generic "Invalid email or password" — never reveals which field was wrong.

### Token helpers — `frontend/lib/auth.ts`

| Function | Description |
|---|---|
| `getAccessToken()` | Read access token from `localStorage` |
| `getRefreshToken()` | Read refresh token from `localStorage` |
| `setTokens(access, refresh)` | Write both tokens to `localStorage` |
| `clearTokens()` | Remove both tokens (logout) |
| `isTokenExpired(token)` | Decode base64 JWT payload, check `exp` with 30 s clock-skew buffer |
| `getRoleFromToken()` | Decode `role` claim from the stored access token |
| `refreshAccessToken()` | Call `POST /auth/refresh`; store new pair on success, clear on failure |

JWT expiry is decoded client-side from the base64 payload — no library required.

### Authenticated fetch — `frontend/lib/apiFetch.ts`

`apiFetch` is a drop-in replacement for the native `fetch` API with the same signature:

```typescript
async function apiFetch(url: string, options?: RequestInit): Promise<Response>
```

Before each request it:

1. Checks whether the stored access token is expired.
2. If expired, calls `refreshAccessToken()` to obtain a fresh pair.
3. Injects `Authorization: Bearer <access_token>` into the request headers.
4. On `401` response — calls `clearTokens()` and redirects to `/login`.

### Auth guard in `page.tsx`

A `useEffect` runs once on mount:

```typescript
useEffect(() => {
  const token = getAccessToken();
  if (!token || isTokenExpired(token)) {
    router.replace("/login");
  }
}, []);
```

The component renders a loading spinner until the guard resolves, preventing the chat UI from flashing before the redirect.

### Session lifecycle

```
User visits /
    │
    ▼
Auth guard (mount effect)
    │
    ├── token missing or expired ──► redirect to /login
    │
    └── token valid ──► render chat UI
                              │
                              ▼
                  User sends message
                              │
                              ▼
                  apiFetch POST /chat/stream
                  ├── token valid      ──► normal request
                  └── token expired    ──► POST /auth/refresh ──► retry request
                                              │
                                              └── refresh fails ──► /login
                              │
                              ▼
                  Logout button clicked
                  clearTokens() + router.replace("/login")
```

### Password change flow

Accessible from the "Change Password" button in the dashboard NAVBAR (Dash):

1. User clicks **Change Password** → modal opens.
2. Modal calls `POST /auth/password-reset/request` with `{ email }` → returns a `reset_token`.
3. Modal immediately calls `POST /auth/password-reset/confirm` with `{ reset_token, new_password }`.
4. On success: modal closes; token is single-use and expires in 30 minutes.

---

## Dashboard Integration

The Plotly Dash dashboard validates the JWT on every page load.  The token is
propagated from Next.js via a `?token=<jwt>` query parameter when the iframe URL
is set, and persisted in `dcc.Store(id="auth-token-store", storage_type="local")`.

| Callback | Guard |
|---|---|
| `store_token_from_url` | Extracts `?token=` and saves to localStorage |
| `display_page` | Calls `_validate_token()` before rendering any page |
| `/admin/users` route | Checks `role == "superuser"` before calling `admin_users_layout()` |
| All admin callbacks | Resolve token via `_resolve_token(stored, url_search)` |

The `_api_call(method, path, token, json_body)` helper in `dashboard/callbacks.py`
sends authenticated requests to the FastAPI backend (`BACKEND_URL` env var,
default `http://127.0.0.1:8181`).

### Environment loading in the dashboard process

The Dash dashboard is a **separate process** from the FastAPI backend.
`dashboard/app.py` includes a `_load_dotenv()` helper (executed at module import
time) that reads `backend/.env` into `os.environ` before any callbacks run.  This
ensures `JWT_SECRET_KEY` is available to `_validate_token()` even when it is not
explicitly exported in the shell.  Env vars already present in the shell always
take precedence.

---

## Admin UI — `/admin/users`

Accessible from the "Admin" link in the dashboard NAVBAR (superusers only;
general users see a 403 notice).  The Next.js sidebar also shows the Admin
nav item only for superusers (role decoded from the JWT with `getRoleFromToken()`).

| Feature | Description |
|---|---|
| **Users tab** | DataTable of all accounts with role/status badges |
| **Add User** | Modal form → `POST /users` |
| **Edit** | Per-row modal pre-filled with user data → `PATCH /users/{id}` |
| **Deactivate / Reactivate** | Per-row toggle → `DELETE /users/{id}` or `PATCH` with `is_active: true` |
| **Audit Log tab** | Full event table (type, actor, target, metadata) |
| **Change Password** | NAVBAR button → global modal → `/auth/password-reset/*` flow |

---

## Security Notes

- `.env` is in `.gitignore` — never commit secrets.
- `data/iceberg/` is in `.gitignore` — the catalog and warehouse are local-only.
- `JWT_SECRET_KEY` must be ≥ 32 random characters (enforced by `AuthService.__init__`).
- Passwords never appear in log output — only hashes are stored and compared.
- Password reset tokens are single-use and expire in 30 minutes.
- All admin endpoints enforce `superuser_only` — a `general` user gets HTTP 403.
