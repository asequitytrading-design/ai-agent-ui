# Auth Module — Execution Plan
**Generated from:** `ai_agent_ui_auth_plan.docx`
**Date:** February 2026
**Stack:** FastAPI + Next.js + Plotly Dash (NOT Streamlit — doc has a typo)

---

## Overview

Add JWT authentication + role-based access control to all three surfaces:
- **Chat** → Next.js frontend (`frontend/`)
- **Dashboard** → Plotly Dash (`dashboard/`)
- **Docs** → MkDocs (read-only, lower priority)

Storage: Apache Iceberg via PyIceberg + SQLite-backed SqlCatalog (local, no extra server).

---

## Phase 1 — Foundation: Iceberg + Repository (4–5 hours)

### 1.1 Install dependencies

```bash
source backend/demoenv/bin/activate
pip install "pyiceberg[sql-sqlite]" python-jose passlib bcrypt python-dotenv
pip freeze > backend/requirements.txt
```

### 1.2 Create `.pyiceberg.yaml` (project root)

```yaml
catalog:
  local:
    type: sql
    uri: sqlite:///data/iceberg/catalog.db
    warehouse: file:///data/iceberg/warehouse
```

### 1.3 Create `auth/create_tables.py`

One-time script to initialise the two Iceberg tables. Run once; idempotent.

**Users table schema:**

| Column | Iceberg Type | Nullable |
|---|---|---|
| user_id | UUIDType (stored as StringType) | No |
| email | StringType | No |
| hashed_password | StringType | No |
| full_name | StringType | No |
| role | StringType (`'superuser'` or `'general'`) | No |
| is_active | BooleanType | No |
| created_at | TimestampType (UTC, microseconds) | No |
| updated_at | TimestampType (UTC, microseconds) | No |
| last_login_at | TimestampType (UTC, microseconds) | Yes |
| password_reset_token | StringType | Yes |
| password_reset_expiry | TimestampType (UTC, microseconds) | Yes |

**Audit log table schema:**

| Column | Iceberg Type |
|---|---|
| event_id | StringType (UUID) |
| event_type | StringType (`USER_CREATED`, `USER_UPDATED`, `USER_DELETED`, `LOGIN`, `PASSWORD_RESET`) |
| actor_user_id | StringType (UUID) |
| target_user_id | StringType (UUID) |
| event_timestamp | TimestampType (UTC, microseconds) |
| metadata | StringType (JSON blob) |

### 1.4 Create `auth/repository.py` — `IcebergUserRepository`

Methods:
- `get_by_email(email: str) -> Optional[dict]` — scan with predicate pushdown
- `get_by_id(user_id: str) -> Optional[dict]`
- `create(user_data: dict) -> dict` — append PyArrow record batch
- `update(user_id: str, updates: dict) -> dict` — read full table as DataFrame, modify row, overwrite
- `delete(user_id: str) -> None` — soft delete: `is_active = False`
- `list_all() -> list[dict]` — full table scan

> **Note on Python 3.9 compat:** Use `Optional[X]` not `X | Y` throughout.

### 1.5 Add to `.gitignore`

```
data/iceberg/
.env
.pyiceberg.yaml
```

> `.pyiceberg.yaml` should be gitignored since it contains the local warehouse path; commit a `.pyiceberg.yaml.example` instead.

---

## Phase 2 — Auth Service + FastAPI Endpoints (4–5 hours)

### 2.1 Create `auth/service.py` — `AuthService`

Methods:
- `hash_password(plain: str) -> str` — bcrypt cost factor 12
- `verify_password(plain: str, hashed: str) -> bool`
- `create_access_token(user_id, email, role) -> str` — HS256, 60-minute TTL
- `create_refresh_token(user_id) -> str` — HS256, 7-day TTL
- `decode_token(token: str) -> dict` — raises `HTTPException(401)` on invalid/expired

Environment variables required (in `backend/.env`):
```
JWT_SECRET_KEY=<min-32-random-chars>
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
```

Add these to `backend/config.py` (`Settings` Pydantic model).

### 2.2 Create `auth/models.py` — Pydantic request/response models

```python
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserContext(BaseModel):
    user_id: str
    email: str
    role: str

class UserCreateRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str  # 'superuser' or 'general'

class UserUpdateRequest(BaseModel):
    full_name: Optional[str]
    email: Optional[str]
    role: Optional[str]
    is_active: Optional[bool]
```

### 2.3 Create `auth/api.py` — FastAPI router

Mount on the main app via `app.include_router(auth_router, prefix="/auth")` in `backend/main.py`.

**Endpoints:**

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | Public | Verify credentials, return JWT pair |
| POST | `/auth/refresh` | Needs refresh token | New access token |
| POST | `/auth/logout` | Authenticated | Add refresh token to deny-list |
| POST | `/auth/password-reset/request` | Authenticated (self) | Generate reset token |
| POST | `/auth/password-reset/confirm` | Authenticated (self) | Apply new password |
| GET | `/users` | Superuser | List all users |
| POST | `/users` | Superuser | Create user |
| GET | `/users/{user_id}` | Superuser | Get single user |
| PATCH | `/users/{user_id}` | Superuser | Edit user |
| DELETE | `/users/{user_id}` | Superuser | Deactivate/delete user |
| GET | `/admin/audit-log` | Superuser | View audit events |

**FastAPI dependency functions (in `auth/dependencies.py`):**

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme)) -> UserContext:
    ...

def superuser_only(user: UserContext = Depends(get_current_user)):
    if user.role != 'superuser':
        raise HTTPException(status_code=403, detail='Not authorized')
    return user
```

### 2.4 Refresh token deny-list

In-memory `set` inside `AuthService` for MVP. Every logout adds the refresh token to the set; `/auth/refresh` checks against it. Note: clears on restart — acceptable for MVP.

### 2.5 Write every CRUD action to the audit log

Every create/update/delete on `/users` must append a row to the `audit_log` Iceberg table. Do this inside the repository, not the route handler.

---

## Phase 3 — Next.js Frontend: Login Page + Session Guard (3–4 hours)

> The original doc mentions Streamlit — **this project uses Next.js**. Adapt accordingly.

### 3.1 New file: `frontend/app/login/page.tsx`

- Client component with email + password inputs
- `POST /auth/login` on submit; on success write `access_token` + `refresh_token` to `localStorage`
- On failure show generic error: "Invalid email or password" (never reveal which field is wrong)
- Redirect to `/` on success via `useRouter().push('/')`

### 3.2 Token helper `frontend/lib/auth.ts`

```typescript
export function getAccessToken(): string | null { ... }
export function setTokens(access: string, refresh: string): void { ... }
export function clearTokens(): void { ... }
export function isTokenExpired(token: string): boolean { ... }  // decode JWT exp claim
export async function refreshAccessToken(): Promise<string | null> { ... }
```

### 3.3 Authenticated fetch wrapper `frontend/lib/apiFetch.ts`

Wraps `fetch()`:
1. Reads access token from `localStorage`
2. If expired, calls `refreshAccessToken()` first
3. Adds `Authorization: Bearer <token>` header
4. On `401` response, clears tokens and redirects to `/login`

Replace direct `fetch('/chat/stream', ...)` calls in `page.tsx` with `apiFetch(...)`.

### 3.4 Auth guard in `frontend/app/page.tsx`

On mount (`useEffect`), check for a valid access token:
```typescript
useEffect(() => {
  if (!getAccessToken()) router.push('/login');
}, []);
```

### 3.5 Logout button

Add a logout button in the chat header (alongside the agent selector). On click: `clearTokens()` + `router.push('/login')`.

### 3.6 Environment variable

Add to `frontend/.env.local`:
```
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8181
```
(Already present — just ensure all auth API calls go through this base URL.)

---

## Phase 4 — Dash Dashboard: Session Guard (2–3 hours)

### 4.1 Token storage in Dash

Add a `dcc.Store(id='auth-token-store', storage_type='local')` to the Dash app layout in `dashboard/app.py`. The frontend will write the JWT here when navigating to the dashboard (via the iframe URL with a token query param, or a shared `localStorage` key).

### 4.2 Token validation helper in `dashboard/callbacks.py`

```python
def _validate_token(token: str) -> Optional[dict]:
    """Decode and validate JWT. Returns payload or None."""
    ...
```

Call at the top of every callback that serves sensitive data (analysis, forecast, compare charts). If `None`, return a redirect to `/login` via `dcc.Location`.

### 4.3 Login redirect in Dash

In `dashboard/layouts.py`, add a minimal unauthenticated state: if the `auth-token-store` is empty or expired, the page layout shows a "Please log in" message with a link to the Next.js login page (`http://localhost:3000/login`).

### 4.4 Token propagation from Next.js → Dash iframe

When the Next.js app renders the Dash iframe, append the token as a query param or rely on `localStorage` (same origin not applicable across ports — use query param approach):
```
http://127.0.0.1:8050/analysis?ticker=AAPL&token=<jwt>
```
Dash reads `?token=` from `dcc.Location.search`, stores it in `dcc.Store`, uses it for all callbacks.

---

## Phase 5 — User Management UI (3–4 hours)

### 5.1 New Dash page: `/admin/users`

Add to `dashboard/layouts.py` a new `admin_users_layout()` factory:
- Dash DataTable showing all users (columns: Full Name, Email, Role, Active, Created At, Last Login)
- "Add User" button → opens a modal (`dbc.Modal`) with a form
- Row click → opens edit modal
- Deactivate toggle in each row
- Superuser-only: check role from `auth-token-store` in the layout callback

### 5.2 Callbacks for User Management

In `dashboard/callbacks.py`, add:
- `load_users_table` — GET `/users` with Bearer token → populate DataTable
- `add_user` — POST `/users` → refresh table
- `edit_user` — PATCH `/users/{id}` → refresh table
- `delete_user` — DELETE `/users/{id}` with confirmation dialog → refresh table

### 5.3 Password Reset self-service

Add a "Change Password" option in the Dash NAVBAR for authenticated general users:
- Opens a modal: Old Password, New Password, Confirm
- Calls `POST /auth/password-reset/request` then `POST /auth/password-reset/confirm`

### 5.4 Audit Log viewer tab

Add a second tab on the `/admin/users` page with a DataTable of all audit log events, paginated, sorted by timestamp descending.

---

## Phase 6 — Seed Script + Hardening (1–2 hours)

### 6.1 `scripts/seed_admin.py`

```bash
python scripts/seed_admin.py
```

Reads `ADMIN_EMAIL` and `ADMIN_PASSWORD` from `.env`, checks if user already exists, and creates a superuser if not. Run once after `auth/create_tables.py`.

Add to `.env`:
```
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=<strong-password>
```

### 6.2 Password strength validation

In `auth/api.py`, before hashing:
- Min 8 characters
- At least one digit
- Raise `HTTPException(400, 'Password too weak')` otherwise

### 6.3 Security checklist before pushing

- [ ] `.env` is in `.gitignore` (never committed)
- [ ] `data/iceberg/` is in `.gitignore`
- [ ] JWT secret is min 32 random chars
- [ ] No plaintext passwords in logs — check `logging_config.py` format strings
- [ ] All admin endpoints use `superuser_only` dependency
- [ ] Password reset tokens are single-use + 30-minute expiry
- [ ] `mkdocs build` passes after adding auth docs page

### 6.4 Update `run.sh`

After the auth module is in place, `run.sh start` should:
1. Check that `data/iceberg/catalog.db` exists; if not, run `python auth/create_tables.py && python scripts/seed_admin.py` first
2. Existing start logic continues unchanged

---

## File Structure to Create

```
ai-agent-ui/
├── auth/
│   ├── __init__.py
│   ├── api.py              # FastAPI router — all auth + user endpoints
│   ├── service.py          # AuthService: bcrypt + JWT
│   ├── repository.py       # IcebergUserRepository
│   ├── models.py           # Pydantic request/response models
│   ├── dependencies.py     # get_current_user, superuser_only
│   └── create_tables.py    # One-time Iceberg table init (run manually)
├── scripts/
│   └── seed_admin.py       # Create first superuser
├── frontend/app/
│   └── login/
│       └── page.tsx        # Login page
├── frontend/lib/
│   ├── auth.ts             # Token helpers
│   └── apiFetch.ts         # Authenticated fetch wrapper
├── .pyiceberg.yaml         # Iceberg catalog config (gitignore; commit .example)
├── .pyiceberg.yaml.example # Template for the above
└── data/iceberg/           # Created at runtime (gitignored)
    ├── catalog.db
    └── warehouse/
```

**Modified files:**
- `backend/main.py` — `app.include_router(auth_router, prefix="/auth")`
- `backend/config.py` — add `jwt_secret_key`, `access_token_expire_minutes`, `refresh_token_expire_days`
- `dashboard/app.py` — add `dcc.Store(id='auth-token-store')`, add `/admin/users` route
- `dashboard/layouts.py` — add `admin_users_layout()`, token check in page callbacks
- `dashboard/callbacks.py` — add `_validate_token()`, user management callbacks, token guard on existing callbacks
- `frontend/app/page.tsx` — add auth guard on mount, logout button, switch fetch → `apiFetch`
- `.gitignore` — add `data/iceberg/`, `.env`, `.pyiceberg.yaml`
- `backend/requirements.txt` — updated after pip install

---

## Recommended Implementation Order

Start here (each item is a self-contained Claude Code prompt session):

1. **Prompt 1** — Phase 1 (Foundation): `.pyiceberg.yaml`, `auth/create_tables.py`, `auth/repository.py`
2. **Prompt 2** — Phase 2a: `auth/service.py`, `auth/models.py`, `auth/dependencies.py`
3. **Prompt 3** — Phase 2b: `auth/api.py` (all endpoints), mount router in `backend/main.py`, update `config.py`
4. **Prompt 4** — Phase 3: Next.js login page, `auth.ts`, `apiFetch.ts`, auth guard in `page.tsx`
5. **Prompt 5** — Phase 4: Dash token store, `_validate_token()`, callback guards, token propagation
6. **Prompt 6** — Phase 5: `/admin/users` Dash page with DataTable + modals
7. **Prompt 7** — Phase 6: `seed_admin.py`, password strength, security hardening, docs update

---

## Key Constraints (from existing codebase)

| Constraint | Detail |
|---|---|
| Python 3.9.13 | Use `Optional[X]` not `X \| Y`. No `match` statements. |
| No `print()` in backend | Use `logging.getLogger(__name__)` everywhere in `auth/` |
| Google-style Sphinx docstrings | All new backend Python files need module + class + method docstrings |
| `mkdocs build` must pass | Add `docs/backend/auth.md` page and link it from `mkdocs.yml` |
| Pydantic models for HTTP bodies | All new request/response models go in `auth/models.py` |
| Tools/agents unchanged | Auth is a separate router — does not touch `agents/` or `tools/` |
| `ChatServer` owns the app | Mount the auth router inside `ChatServer.__init__()` or `_configure_routes()` |

---

## Risks to Watch

| Risk | Mitigation |
|---|---|
| PyIceberg COW updates slow | Fine for <10k users. COW rewrite is acceptable. |
| JWT secret leaked | Add `.env` to `.gitignore` before writing any JWT code |
| Dash callbacks bypass auth | Add `_validate_token()` as the **first line** of every sensitive callback |
| Refresh token not invalidated on logout | In-memory deny-list in `AuthService`; acceptable for MVP |
| SQLite WAL conflicts | SQLite WAL mode handles single-server concurrency fine |
| Token propagation to Dash iframe | Use `?token=<jwt>` query param — cross-port `localStorage` won't work |

---

## Definition of Done

- [ ] `python auth/create_tables.py` creates both Iceberg tables without error
- [ ] `python scripts/seed_admin.py` creates the initial superuser
- [ ] `POST /auth/login` returns a JWT pair for valid credentials
- [ ] `GET /users` returns 403 for a general user token
- [ ] Next.js `/login` page authenticates and redirects to chat
- [ ] Unauthenticated access to `/` redirects to `/login`
- [ ] Logout clears tokens and redirects to `/login`
- [ ] Dash dashboard validates token on load; shows "please log in" if missing
- [ ] Superuser can create/edit/deactivate users via `/admin/users`
- [ ] All audit events written to Iceberg `audit_log`
- [ ] `mkdocs build` passes
- [ ] Pre-push hook passes (no bare `print()`, docstrings present)
