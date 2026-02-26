"""FastAPI router for all authentication and user-management endpoints.

Mount this router in ``backend/main.py`` with no prefix so that the paths
defined here (``/auth/...``, ``/users/...``, ``/admin/...``) are exposed
directly at the root of the API::

    from auth.api import create_auth_router
    app.include_router(create_auth_router())

Endpoints
---------

Auth
~~~~
``POST /auth/login``
    JSON-body login — returns an access + refresh JWT pair.

``POST /auth/login/form``
    OAuth2 form-based login — used by the OpenAPI "Authorize" button.

``POST /auth/refresh``
    Exchange a valid refresh token for a new access token.

``POST /auth/logout``
    Revoke the supplied refresh token (adds its JTI to the deny-list).

``POST /auth/password-reset/request``
    Generate a single-use password reset token for the authenticated user.
    **Development note:** the token is returned in the response body.  In
    production this should be sent via email and the body should only
    return a success message.

``POST /auth/password-reset/confirm``
    Apply a new password using the reset token issued above.

Users (superuser only)
~~~~~~~~~~~~~~~~~~~~~~
``GET  /users``             — List all users.
``POST /users``             — Create a new user.
``GET  /users/{user_id}``   — Get a single user.
``PATCH /users/{user_id}``  — Edit a user's details.
``DELETE /users/{user_id}`` — Soft-delete a user (``is_active = False``).

Admin (superuser only)
~~~~~~~~~~~~~~~~~~~~~~
``GET /admin/audit-log``    — List all audit log events, newest first.

OAuth / SSO
~~~~~~~~~~~
``GET  /auth/oauth/providers``              — List enabled OAuth providers.
``GET  /auth/oauth/{provider}/authorize``   — Build consent URL + issue state.
``POST /auth/oauth/callback``               — Exchange code for our JWT pair.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from auth.dependencies import get_auth_service, get_current_user, superuser_only
from auth.models import (
    LoginRequest,
    LogoutRequest,
    OAuthAuthorizeResponse,
    OAuthCallbackRequest,
    OAuthProvider,
    PasswordResetConfirmBody,
    PasswordResetRequestBody,
    RefreshRequest,
    TokenResponse,
    UserContext,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from auth.oauth_service import OAuthService
from auth.repository import IcebergUserRepository
from auth.service import AuthService

_logger = logging.getLogger(__name__)  # module-level logger (shared)


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_repo() -> IcebergUserRepository:
    """Return the application-wide :class:`~auth.repository.IcebergUserRepository`.

    The repository is constructed once and cached for the process lifetime.
    The constructor changes the working directory to the project root so that
    the Iceberg catalog paths in ``.pyiceberg.yaml`` resolve correctly.

    Returns:
        The cached :class:`~auth.repository.IcebergUserRepository` instance.
    """
    return IcebergUserRepository()


@lru_cache(maxsize=1)
def _get_oauth_svc() -> OAuthService:
    """Return the application-wide :class:`~auth.oauth_service.OAuthService`.

    The service holds the in-memory OAuth state store, so it must be a
    singleton to ensure state persists between the ``/authorize`` redirect
    and the ``/callback`` exchange.

    Returns:
        The cached :class:`~auth.oauth_service.OAuthService` instance.
    """
    from config import get_settings

    return OAuthService(get_settings())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_to_response(user: Dict[str, Any]) -> UserResponse:
    """Convert a raw user dict from the repository to a :class:`~auth.models.UserResponse`.

    Sensitive fields (``hashed_password``, ``password_reset_token``,
    ``password_reset_expiry``) are intentionally excluded.

    Args:
        user: A user dict as returned by :class:`~auth.repository.IcebergUserRepository`.

    Returns:
        A :class:`~auth.models.UserResponse` safe to include in API responses.
    """

    def _iso(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        full_name=user["full_name"],
        role=user["role"],
        is_active=user["is_active"],
        created_at=_iso(user.get("created_at")),
        updated_at=_iso(user.get("updated_at")),
        last_login_at=_iso(user.get("last_login_at")),
    )


def _require_active_user(user: Optional[Dict[str, Any]], email: str) -> Dict[str, Any]:
    """Raise HTTP 401 if the user is not found or is deactivated.

    Uses a generic "Invalid credentials" message to avoid leaking whether
    the email exists in the system.

    Args:
        user: User dict from the repository, or ``None`` if not found.
        email: The email that was looked up (used only for debug logging).

    Returns:
        The user dict if valid and active.

    Raises:
        HTTPException: 401 with ``"Invalid credentials"`` detail.
    """
    if user is None or not user.get("is_active", False):
        _logger.warning("Login failed for email=%s (not found or inactive).", email)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_auth_router() -> APIRouter:
    """Build and return the auth / user management :class:`~fastapi.APIRouter`.

    Call once from ``backend/main.py`` and pass the result to
    ``app.include_router()``.

    Returns:
        A configured :class:`~fastapi.APIRouter` with all auth and user
        management endpoints registered.

    Example:
        >>> from auth.api import create_auth_router
        >>> router = create_auth_router()  # doctest: +SKIP
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # POST /auth/login  (JSON body)
    # ------------------------------------------------------------------

    @router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
    def login(
        body: LoginRequest,
        service: AuthService = Depends(get_auth_service),
    ) -> TokenResponse:
        """Authenticate a user and return a JWT access + refresh token pair.

        Args:
            body: :class:`~auth.models.LoginRequest` with ``email`` and
                ``password``.
            service: Injected :class:`~auth.service.AuthService`.

        Returns:
            A :class:`~auth.models.TokenResponse` with ``access_token``,
            ``refresh_token``, and ``token_type``.

        Raises:
            HTTPException: 401 if credentials are invalid or the account is
                deactivated.
        """
        repo = _get_repo()
        user = repo.get_by_email(str(body.email))
        user = _require_active_user(user, str(body.email))

        if not service.verify_password(body.password, user["hashed_password"]):
            _logger.warning("Login failed for email=%s (wrong password).", body.email)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Update last_login_at
        repo.update(user["user_id"], {"last_login_at": datetime.utcnow()})
        repo.append_audit_event(
            "LOGIN",
            actor_user_id=user["user_id"],
            target_user_id=user["user_id"],
        )

        access = service.create_access_token(
            user_id=user["user_id"],
            email=user["email"],
            role=user["role"],
        )
        refresh = service.create_refresh_token(user_id=user["user_id"])
        _logger.info("User logged in: user_id=%s", user["user_id"])
        return TokenResponse(access_token=access, refresh_token=refresh)

    # ------------------------------------------------------------------
    # POST /auth/login/form  (OAuth2 form — for OpenAPI "Authorize" button)
    # ------------------------------------------------------------------

    @router.post("/auth/login/form", response_model=TokenResponse, tags=["auth"])
    def login_form(
        form: OAuth2PasswordRequestForm = Depends(),
        service: AuthService = Depends(get_auth_service),
    ) -> TokenResponse:
        """OAuth2 form-based login for the OpenAPI documentation UI.

        Accepts ``application/x-www-form-urlencoded`` with ``username`` and
        ``password`` fields (OAuth2 convention — ``username`` is the email).

        Args:
            form: :class:`~fastapi.security.OAuth2PasswordRequestForm`.
            service: Injected :class:`~auth.service.AuthService`.

        Returns:
            A :class:`~auth.models.TokenResponse`.

        Raises:
            HTTPException: 401 if credentials are invalid.
        """
        repo = _get_repo()
        user = repo.get_by_email(form.username)
        user = _require_active_user(user, form.username)

        if not service.verify_password(form.password, user["hashed_password"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        repo.update(user["user_id"], {"last_login_at": datetime.utcnow()})
        repo.append_audit_event("LOGIN", user["user_id"], user["user_id"])

        access = service.create_access_token(
            user_id=user["user_id"],
            email=user["email"],
            role=user["role"],
        )
        refresh = service.create_refresh_token(user_id=user["user_id"])
        return TokenResponse(access_token=access, refresh_token=refresh)

    # ------------------------------------------------------------------
    # POST /auth/refresh
    # ------------------------------------------------------------------

    @router.post("/auth/refresh", response_model=TokenResponse, tags=["auth"])
    def refresh_token(
        body: RefreshRequest,
        service: AuthService = Depends(get_auth_service),
    ) -> TokenResponse:
        """Exchange a valid refresh token for a new access token.

        The old refresh token is revoked and a new refresh token is issued
        (rotation).

        Args:
            body: :class:`~auth.models.RefreshRequest` with ``refresh_token``.
            service: Injected :class:`~auth.service.AuthService`.

        Returns:
            A :class:`~auth.models.TokenResponse` with fresh tokens.

        Raises:
            HTTPException: 401 if the refresh token is invalid, expired, or
                revoked.
        """
        payload = service.decode_token(body.refresh_token, expected_type="refresh")
        user_id: str = payload["sub"]

        repo = _get_repo()
        user = repo.get_by_id(user_id)
        if user is None or not user.get("is_active", False):
            raise HTTPException(status_code=401, detail="User not found or deactivated")

        # Rotate: revoke old refresh token, issue new pair
        service.revoke_refresh_token(body.refresh_token)
        access = service.create_access_token(
            user_id=user["user_id"],
            email=user["email"],
            role=user["role"],
        )
        new_refresh = service.create_refresh_token(user_id=user["user_id"])
        _logger.info("Token refreshed for user_id=%s", user_id)
        return TokenResponse(access_token=access, refresh_token=new_refresh)

    # ------------------------------------------------------------------
    # POST /auth/logout
    # ------------------------------------------------------------------

    @router.post("/auth/logout", tags=["auth"])
    def logout(
        body: LogoutRequest,
        service: AuthService = Depends(get_auth_service),
        current_user: UserContext = Depends(get_current_user),
    ) -> Dict[str, str]:
        """Invalidate the supplied refresh token.

        Adds the token's JTI to the in-memory deny-list so it cannot be used
        to obtain new access tokens.

        Args:
            body: :class:`~auth.models.LogoutRequest` with ``refresh_token``.
            service: Injected :class:`~auth.service.AuthService`.
            current_user: Authenticated :class:`~auth.models.UserContext`.

        Returns:
            A dict ``{"detail": "Logged out successfully"}``.
        """
        service.revoke_refresh_token(body.refresh_token)
        _logger.info("User logged out: user_id=%s", current_user.user_id)
        return {"detail": "Logged out successfully"}

    # ------------------------------------------------------------------
    # POST /auth/password-reset/request
    # ------------------------------------------------------------------

    @router.post("/auth/password-reset/request", tags=["auth"])
    def password_reset_request(
        body: PasswordResetRequestBody,
        current_user: UserContext = Depends(get_current_user),
    ) -> Dict[str, str]:
        """Generate a single-use password reset token for the requesting user.

        The authenticated user may only reset their **own** password.  The
        reset token expires in 30 minutes.

        **Development note:** the token is returned in the response.  In
        production it should be delivered by email and the response body
        should only confirm that a reset email was sent.

        Args:
            body: :class:`~auth.models.PasswordResetRequestBody` with
                ``email``.  Must match the authenticated user's email.
            current_user: Authenticated :class:`~auth.models.UserContext`.

        Returns:
            A dict containing ``"reset_token"`` (development only) and a
            ``"detail"`` message.

        Raises:
            HTTPException: 403 if the email does not match the caller's email.
            HTTPException: 404 if the user record cannot be found.
        """
        if str(body.email).lower() != current_user.email.lower():
            raise HTTPException(
                status_code=403,
                detail="You may only reset your own password.",
            )

        repo = _get_repo()
        user = repo.get_by_id(current_user.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        reset_token = str(uuid.uuid4())
        expiry = datetime.utcnow() + timedelta(minutes=30)
        repo.update(
            current_user.user_id,
            {
                "password_reset_token": reset_token,
                "password_reset_expiry": expiry,
            },
        )
        repo.append_audit_event(
            "PASSWORD_RESET",
            actor_user_id=current_user.user_id,
            target_user_id=current_user.user_id,
            metadata={"stage": "request"},
        )
        _logger.info("Password reset requested by user_id=%s", current_user.user_id)
        # NOTE: return token in response for development; send by email in production.
        return {
            "detail": "Password reset token generated (development: token included in response).",
            "reset_token": reset_token,
        }

    # ------------------------------------------------------------------
    # POST /auth/password-reset/confirm
    # ------------------------------------------------------------------

    @router.post("/auth/password-reset/confirm", tags=["auth"])
    def password_reset_confirm(
        body: PasswordResetConfirmBody,
        current_user: UserContext = Depends(get_current_user),
        service: AuthService = Depends(get_auth_service),
    ) -> Dict[str, str]:
        """Apply a new password using a previously issued reset token.

        The reset token is single-use and expires 30 minutes after issue.

        Args:
            body: :class:`~auth.models.PasswordResetConfirmBody` with
                ``reset_token`` and ``new_password``.
            current_user: Authenticated :class:`~auth.models.UserContext`.
            service: Injected :class:`~auth.service.AuthService`.

        Returns:
            A dict ``{"detail": "Password updated successfully"}``.

        Raises:
            HTTPException: 400 if the token is invalid, expired, or the
                password does not meet strength requirements.
            HTTPException: 404 if the user record cannot be found.
        """
        AuthService.validate_password_strength(body.new_password)

        repo = _get_repo()
        user = repo.get_by_id(current_user.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        stored_token = user.get("password_reset_token")
        expiry = user.get("password_reset_expiry")

        if not stored_token or stored_token != body.reset_token:
            raise HTTPException(status_code=400, detail="Invalid reset token")

        if expiry is not None:
            expiry_naive = expiry.replace(tzinfo=None) if expiry.tzinfo else expiry
            if datetime.utcnow() > expiry_naive:
                raise HTTPException(status_code=400, detail="Reset token has expired")

        new_hash = service.hash_password(body.new_password)
        repo.update(
            current_user.user_id,
            {
                "hashed_password": new_hash,
                "password_reset_token": None,
                "password_reset_expiry": None,
            },
        )
        repo.append_audit_event(
            "PASSWORD_RESET",
            actor_user_id=current_user.user_id,
            target_user_id=current_user.user_id,
            metadata={"stage": "confirm"},
        )
        _logger.info("Password reset completed for user_id=%s", current_user.user_id)
        return {"detail": "Password updated successfully"}

    # ------------------------------------------------------------------
    # GET /users  (superuser only)
    # ------------------------------------------------------------------

    @router.get("/users", response_model=List[UserResponse], tags=["users"])
    def list_users(
        _: UserContext = Depends(superuser_only),
    ) -> List[UserResponse]:
        """Return all users in the system.

        Args:
            _: Superuser guard — raises 403 for non-superusers.

        Returns:
            A list of :class:`~auth.models.UserResponse` objects.
        """
        repo = _get_repo()
        users = repo.list_all()
        return [_user_to_response(u) for u in users]

    # ------------------------------------------------------------------
    # POST /users  (superuser only)
    # ------------------------------------------------------------------

    @router.post("/users", response_model=UserResponse, status_code=201, tags=["users"])
    def create_user(
        body: UserCreateRequest,
        caller: UserContext = Depends(superuser_only),
        service: AuthService = Depends(get_auth_service),
    ) -> UserResponse:
        """Create a new user account.

        Args:
            body: :class:`~auth.models.UserCreateRequest` with email,
                password, full_name, and role.
            caller: Superuser guard.
            service: Injected :class:`~auth.service.AuthService`.

        Returns:
            The newly created :class:`~auth.models.UserResponse`.

        Raises:
            HTTPException: 400 if the password is too weak.
            HTTPException: 409 if a user with that email already exists.
        """
        AuthService.validate_password_strength(body.password)

        repo = _get_repo()
        if repo.get_by_email(str(body.email)) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A user with email '{body.email}' already exists.",
            )

        hashed = service.hash_password(body.password)
        user = repo.create(
            {
                "email": str(body.email),
                "hashed_password": hashed,
                "full_name": body.full_name,
                "role": body.role,
            }
        )
        repo.append_audit_event(
            "USER_CREATED",
            actor_user_id=caller.user_id,
            target_user_id=user["user_id"],
            metadata={"email": user["email"], "role": user["role"]},
        )
        _logger.info(
            "User created: user_id=%s by superuser=%s", user["user_id"], caller.user_id
        )
        return _user_to_response(user)

    # ------------------------------------------------------------------
    # GET /users/{user_id}  (superuser only)
    # ------------------------------------------------------------------

    @router.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
    def get_user(
        user_id: str,
        _: UserContext = Depends(superuser_only),
    ) -> UserResponse:
        """Fetch a single user by UUID.

        Args:
            user_id: UUID string from the URL path.
            _: Superuser guard.

        Returns:
            The :class:`~auth.models.UserResponse` for the requested user.

        Raises:
            HTTPException: 404 if no user with that ID exists.
        """
        repo = _get_repo()
        user = repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        return _user_to_response(user)

    # ------------------------------------------------------------------
    # PATCH /users/{user_id}  (superuser only)
    # ------------------------------------------------------------------

    @router.patch("/users/{user_id}", response_model=UserResponse, tags=["users"])
    def update_user(
        user_id: str,
        body: UserUpdateRequest,
        caller: UserContext = Depends(superuser_only),
    ) -> UserResponse:
        """Edit a user's details.

        Only fields present in the request body are updated.  ``user_id`` and
        ``created_at`` are immutable.

        Args:
            user_id: UUID string from the URL path.
            body: :class:`~auth.models.UserUpdateRequest` — all fields optional.
            caller: Superuser guard + injected caller context for audit log.

        Returns:
            The updated :class:`~auth.models.UserResponse`.

        Raises:
            HTTPException: 404 if no user with that ID exists.
            HTTPException: 409 if the new email is already in use.
        """
        repo = _get_repo()
        if repo.get_by_id(user_id) is None:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")

        updates: Dict[str, Any] = {
            k: v
            for k, v in body.model_dump().items()
            if v is not None
        }

        # Email uniqueness check
        if "email" in updates:
            existing = repo.get_by_email(str(updates["email"]))
            if existing is not None and existing["user_id"] != user_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"Email '{updates['email']}' is already in use.",
                )

        updated = repo.update(user_id, updates)
        repo.append_audit_event(
            "USER_UPDATED",
            actor_user_id=caller.user_id,
            target_user_id=user_id,
            metadata={"fields_changed": list(updates.keys())},
        )
        _logger.info(
            "User updated: user_id=%s fields=%s by superuser=%s",
            user_id,
            list(updates.keys()),
            caller.user_id,
        )
        return _user_to_response(updated)

    # ------------------------------------------------------------------
    # DELETE /users/{user_id}  (superuser only)
    # ------------------------------------------------------------------

    @router.delete("/users/{user_id}", tags=["users"])
    def delete_user(
        user_id: str,
        caller: UserContext = Depends(superuser_only),
    ) -> Dict[str, str]:
        """Soft-delete a user by setting ``is_active = False``.

        Args:
            user_id: UUID string from the URL path.
            caller: Superuser guard.

        Returns:
            A dict ``{"detail": "User deactivated"}``.

        Raises:
            HTTPException: 404 if no user with that ID exists.
            HTTPException: 400 if the caller tries to delete themselves.
        """
        if user_id == caller.user_id:
            raise HTTPException(
                status_code=400, detail="Superusers cannot deactivate their own account."
            )
        repo = _get_repo()
        if repo.get_by_id(user_id) is None:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")

        repo.delete(user_id)
        repo.append_audit_event(
            "USER_DELETED",
            actor_user_id=caller.user_id,
            target_user_id=user_id,
        )
        _logger.info(
            "User soft-deleted: user_id=%s by superuser=%s", user_id, caller.user_id
        )
        return {"detail": "User deactivated"}

    # ------------------------------------------------------------------
    # GET /auth/oauth/providers
    # ------------------------------------------------------------------

    @router.get("/auth/oauth/providers", tags=["oauth"])
    def list_oauth_providers() -> Dict[str, List[str]]:
        """List OAuth providers that are currently enabled.

        A provider is considered enabled when its client ID / app ID is
        configured in :class:`~config.Settings`.  The frontend uses this
        endpoint to show or hide the SSO buttons dynamically.

        Returns:
            A dict ``{"providers": ["google", "facebook"]}`` listing only
            providers with non-empty credentials.
        """
        from config import get_settings

        settings = get_settings()
        providers: List[str] = []
        if settings.google_client_id:
            providers.append(OAuthProvider.google.value)
        if settings.facebook_app_id:
            providers.append(OAuthProvider.facebook.value)
        return {"providers": providers}

    # ------------------------------------------------------------------
    # GET /auth/oauth/{provider}/authorize
    # ------------------------------------------------------------------

    @router.get("/auth/oauth/{provider}/authorize", response_model=OAuthAuthorizeResponse, tags=["oauth"])
    def oauth_authorize(
        provider: str,
        code_challenge: str,
    ) -> OAuthAuthorizeResponse:
        """Generate a provider consent URL and a server-side CSRF state token.

        The frontend should:
        1. Generate a ``code_verifier`` locally (see ``frontend/lib/oauth.ts``).
        2. Compute ``code_challenge = base64url(SHA-256(verifier))``.
        3. Call this endpoint with the ``code_challenge`` query parameter.
        4. Store ``code_verifier`` and ``state`` in ``sessionStorage``.
        5. Redirect the browser to ``authorize_url``.

        Args:
            provider: OAuth provider — ``"google"`` or ``"facebook"``.
            code_challenge: PKCE challenge (base64url SHA-256 of the verifier).

        Returns:
            :class:`~auth.models.OAuthAuthorizeResponse` with ``state`` and
            ``authorize_url``.

        Raises:
            HTTPException: 400 if *provider* is not supported.
            HTTPException: 503 if the provider's credentials are not
                configured.
        """
        try:
            provider_enum = OAuthProvider(provider)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unsupported OAuth provider: '{provider}'")

        from config import get_settings

        settings = get_settings()
        if provider_enum == OAuthProvider.google and not settings.google_client_id:
            raise HTTPException(status_code=503, detail="Google SSO is not configured.")
        if provider_enum == OAuthProvider.facebook and not settings.facebook_app_id:
            raise HTTPException(status_code=503, detail="Facebook SSO is not configured.")

        oauth_svc = _get_oauth_svc()
        try:
            state, authorize_url = oauth_svc.generate_authorize_url(
                provider_enum.value, code_challenge
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        _logger.info("OAuth authorize: provider=%s", provider)
        return OAuthAuthorizeResponse(state=state, authorize_url=authorize_url)

    # ------------------------------------------------------------------
    # POST /auth/oauth/callback
    # ------------------------------------------------------------------

    @router.post("/auth/oauth/callback", response_model=TokenResponse, tags=["oauth"])
    def oauth_callback(
        body: OAuthCallbackRequest,
        service: AuthService = Depends(get_auth_service),
    ) -> TokenResponse:
        """Exchange an OAuth authorization code for our own JWT pair.

        Called by the frontend callback page after the provider redirects
        back with ``?code=...&state=...`` query parameters.

        Steps performed:
        1. Validate the CSRF state token (single-use, 10-minute TTL).
        2. Exchange the authorization code with the provider.
        3. Upsert the user via
           :meth:`~auth.repository.IcebergUserRepository.get_or_create_by_oauth`.
        4. Issue an access + refresh token pair.
        5. Record an ``OAUTH_LOGIN`` audit event.

        Args:
            body: :class:`~auth.models.OAuthCallbackRequest` with
                ``provider``, ``code``, ``state``, and optionally
                ``code_verifier``.
            service: Injected :class:`~auth.service.AuthService`.

        Returns:
            A :class:`~auth.models.TokenResponse` (same shape as
            ``POST /auth/login``).

        Raises:
            HTTPException: 400 if the state is invalid or expired.
            HTTPException: 400 if the provider rejects the code exchange.
            HTTPException: 403 if the resulting user account is deactivated.
        """
        oauth_svc = _get_oauth_svc()
        repo = _get_repo()

        # 1. Validate state (CSRF protection).
        if not oauth_svc.validate_state(body.state, body.provider.value):
            _logger.warning("Invalid OAuth state token: provider=%s", body.provider)
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state token.")

        # 2. Exchange code with the provider.
        try:
            if body.provider == OAuthProvider.google:
                verifier = body.code_verifier or ""
                user_info = oauth_svc.exchange_google_code(body.code, verifier)
            else:
                user_info = oauth_svc.exchange_facebook_code(body.code)
        except Exception as exc:
            _logger.error("OAuth code exchange failed: provider=%s error=%s", body.provider, exc)
            raise HTTPException(
                status_code=400,
                detail=f"OAuth token exchange failed: {exc}",
            )

        # 3. Upsert user in our database.
        user = repo.get_or_create_by_oauth(
            provider=user_info["provider"],
            oauth_sub=user_info["sub"],
            email=user_info["email"],
            full_name=user_info["full_name"],
            picture_url=user_info.get("picture"),
        )

        if not user.get("is_active", False):
            raise HTTPException(status_code=403, detail="Account is deactivated.")

        # Update last_login_at (already done inside get_or_create_by_oauth for
        # existing users, but ensure it for newly created accounts too).
        repo.update(user["user_id"], {"last_login_at": datetime.utcnow()})

        # 4. Issue our JWT pair.
        access = service.create_access_token(
            user_id=user["user_id"],
            email=user["email"],
            role=user["role"],
        )
        refresh = service.create_refresh_token(user_id=user["user_id"])

        # 5. Audit event.
        repo.append_audit_event(
            "OAUTH_LOGIN",
            actor_user_id=user["user_id"],
            target_user_id=user["user_id"],
            metadata={"provider": body.provider.value, "email": user["email"]},
        )

        _logger.info(
            "OAuth login: user_id=%s provider=%s email=%s",
            user["user_id"],
            body.provider,
            user["email"],
        )
        return TokenResponse(access_token=access, refresh_token=refresh)

    # ------------------------------------------------------------------
    # GET /admin/audit-log  (superuser only)
    # ------------------------------------------------------------------

    @router.get("/admin/audit-log", tags=["admin"])
    def get_audit_log(
        _: UserContext = Depends(superuser_only),
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return all audit log events, sorted newest-first.

        Args:
            _: Superuser guard.

        Returns:
            A dict ``{"events": [...]}`` where each element is an audit log
            entry with ``event_id``, ``event_type``, ``actor_user_id``,
            ``target_user_id``, ``event_timestamp`` (ISO-8601), and
            ``metadata`` (JSON string or ``None``).
        """
        repo = _get_repo()
        raw_events = repo.list_audit_events()
        events = []
        for ev in raw_events:
            d = dict(ev)
            ts = d.get("event_timestamp")
            if ts is not None and hasattr(ts, "isoformat"):
                d["event_timestamp"] = ts.isoformat()
            events.append(d)
        return {"events": events}

    return router