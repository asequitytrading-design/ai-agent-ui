"""Pydantic request and response models for the auth module.

All HTTP request bodies and response bodies for the ``/auth`` and ``/users``
endpoints are defined here.  Keeping them in one place makes it easy to audit
the auth surface and to generate OpenAPI documentation.

Models
------
- :class:`LoginRequest` — credentials for ``POST /auth/login``
- :class:`TokenResponse` — JWT pair returned on successful login or refresh
- :class:`UserContext` — decoded JWT payload; used as a FastAPI dependency
- :class:`UserCreateRequest` — superuser creates a new user
- :class:`UserUpdateRequest` — superuser edits an existing user
- :class:`UserResponse` — public user representation (no password hash)
- :class:`PasswordResetRequestBody` — initiates a self-service password reset
- :class:`PasswordResetConfirmBody` — completes a self-service password reset
- :class:`OAuthProvider` — enum of supported OAuth providers
- :class:`OAuthAuthorizeResponse` — response from ``GET /auth/oauth/{provider}/authorize``
- :class:`OAuthCallbackRequest` — request body for ``POST /auth/oauth/callback``
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /auth/login``.

    Attributes:
        email: The user's registered email address.
        password: The plaintext password (never stored; compared against the
            bcrypt hash).
    """

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT pair returned on successful authentication or token refresh.

    Attributes:
        access_token: Short-lived JWT (default 60 minutes).  Must be sent in
            the ``Authorization: Bearer <token>`` header on every protected
            request.
        refresh_token: Long-lived JWT (default 7 days).  Used only on
            ``POST /auth/refresh`` to obtain a new access token.
        token_type: Always ``"bearer"``.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserContext(BaseModel):
    """Decoded JWT payload injected by the :func:`~auth.dependencies.get_current_user` dependency.

    Attributes:
        user_id: UUID string of the authenticated user.
        email: Email address extracted from the JWT payload.
        role: Either ``"superuser"`` or ``"general"``.
    """

    user_id: str
    email: str
    role: str


class UserCreateRequest(BaseModel):
    """Request body for ``POST /users`` (superuser only).

    Attributes:
        email: Email address for the new account.  Must be unique.
        password: Plaintext initial password.  Validated for minimum strength
            server-side (min 8 chars, at least one digit).
        full_name: Display name shown in the UI.
        role: Account role — ``"superuser"`` or ``"general"``.  Defaults to
            ``"general"``.
    """

    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1)
    role: str = "general"


class UserUpdateRequest(BaseModel):
    """Request body for ``PATCH /users/{user_id}`` (superuser only).

    All fields are optional — only supplied fields are updated.

    Attributes:
        full_name: New display name.
        email: New email address.  Must be unique across all users.
        role: New role — ``"superuser"`` or ``"general"``.
        is_active: Set to ``False`` to deactivate the account (soft delete).
    """

    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """Public user representation returned by ``GET /users`` and related endpoints.

    The ``hashed_password``, ``password_reset_token``, and
    ``password_reset_expiry`` fields are never exposed via the API.

    Attributes:
        user_id: UUID string.
        email: Email address.
        full_name: Display name.
        role: ``"superuser"`` or ``"general"``.
        is_active: Whether the account is active.
        created_at: ISO-8601 string of the creation timestamp (UTC).
        updated_at: ISO-8601 string of the last modification timestamp (UTC).
        last_login_at: ISO-8601 string of the most recent login, or ``None``.
    """

    user_id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_login_at: Optional[str] = None


class PasswordResetRequestBody(BaseModel):
    """Request body for ``POST /auth/password-reset/request``.

    Attributes:
        email: Email of the account whose password should be reset.
    """

    email: EmailStr


class PasswordResetConfirmBody(BaseModel):
    """Request body for ``POST /auth/password-reset/confirm``.

    Attributes:
        reset_token: The single-use token previously issued by
            ``POST /auth/password-reset/request``.
        new_password: The new plaintext password (min 8 chars, one digit).
    """

    reset_token: str
    new_password: str = Field(..., min_length=8)


class RefreshRequest(BaseModel):
    """Request body for ``POST /auth/refresh``.

    Attributes:
        refresh_token: The long-lived refresh token issued at login.
    """

    refresh_token: str


class LogoutRequest(BaseModel):
    """Request body for ``POST /auth/logout``.

    Attributes:
        refresh_token: The refresh token to invalidate server-side.
    """

    refresh_token: str


# ---------------------------------------------------------------------------
# SSO / OAuth2 models
# ---------------------------------------------------------------------------


class OAuthProvider(str, Enum):
    """Supported OAuth2 SSO providers.

    Attributes:
        google: Google OAuth2 (OpenID Connect).
        facebook: Facebook OAuth2 (Graph API).
    """

    google = "google"
    facebook = "facebook"


class OAuthAuthorizeResponse(BaseModel):
    """Response body for ``GET /auth/oauth/{provider}/authorize``.

    Attributes:
        state: CSRF state token generated server-side.  The frontend must
            store this and pass it back in :class:`OAuthCallbackRequest`.
        authorize_url: Full provider consent URL to redirect the browser to.
    """

    state: str
    authorize_url: str


class OAuthCallbackRequest(BaseModel):
    """Request body for ``POST /auth/oauth/callback``.

    Sent by the frontend callback page after the provider redirects back
    with an authorization code.

    Attributes:
        provider: The OAuth provider that issued the code.
        code: Authorization code from the provider's redirect.
        state: The CSRF state token originally returned by
            ``GET /auth/oauth/{provider}/authorize``.
        code_verifier: PKCE code verifier stored in ``sessionStorage``
            during the authorize step.  Required for Google; optional
            (and ignored) for Facebook.
    """

    provider: OAuthProvider
    code: str
    state: str
    code_verifier: Optional[str] = None
