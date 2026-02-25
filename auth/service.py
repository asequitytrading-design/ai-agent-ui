"""Authentication service providing JWT creation/validation and password hashing.

:class:`AuthService` is a stateful singleton that encapsulates:

- Password hashing and verification via ``passlib`` (bcrypt, cost factor 12).
- JWT access token creation (HS256, configurable TTL).
- JWT refresh token creation (HS256, configurable TTL).
- JWT decoding and validation.
- An in-memory refresh-token deny-list to support logout.

Usage::

    service = AuthService(
        secret_key="your-32-char-random-secret",
        access_expire_minutes=60,
        refresh_expire_days=7,
    )

    hashed = service.hash_password("my-secret-password")
    ok = service.verify_password("my-secret-password", hashed)

    access = service.create_access_token(user_id="...", email="...", role="general")
    refresh = service.create_refresh_token(user_id="...")

    payload = service.decode_token(access)

Note on the deny-list
---------------------
The deny-list lives in memory.  It is cleared when the process restarts.
This is acceptable for the MVP (single-server deployment).  For multi-process
or multi-server deployments the deny-list should be backed by Redis or an
Iceberg table.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_ACCESS_TOKEN_TYPE = "access"
_REFRESH_TOKEN_TYPE = "refresh"

# bcrypt cost factor 12 — good balance of security and speed (~250ms per hash)
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


class AuthService:
    """Stateful authentication service for JWT lifecycle and password management.

    One instance should be created per process and reused across all requests
    so the in-memory :attr:`_deny_list` persists across calls.

    Attributes:
        _secret_key: HMAC secret used to sign and verify JWTs.
        _access_expire_minutes: Lifetime of an access token in minutes.
        _refresh_expire_days: Lifetime of a refresh token in days.
        _deny_list: Set of revoked refresh token JTI strings.  Tokens whose
            JTI appears here are rejected by :meth:`decode_token`.
    """

    def __init__(
        self,
        secret_key: str,
        access_expire_minutes: int = 60,
        refresh_expire_days: int = 7,
    ) -> None:
        """Initialise the service with signing credentials and TTLs.

        Args:
            secret_key: HMAC-SHA256 secret.  Must be at least 32 random
                characters.  Store in ``.env`` as ``JWT_SECRET_KEY``.
            access_expire_minutes: Access token lifetime in minutes.
                Defaults to ``60``.
            refresh_expire_days: Refresh token lifetime in days.
                Defaults to ``7``.

        Raises:
            ValueError: If *secret_key* is empty or shorter than 32 characters.
        """
        if not secret_key or len(secret_key) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        self._secret_key = secret_key
        self._access_expire_minutes = access_expire_minutes
        self._refresh_expire_days = refresh_expire_days
        self._deny_list: Set[str] = set()
        logger.info(
            "AuthService initialised (access_ttl=%dm, refresh_ttl=%dd).",
            access_expire_minutes,
            refresh_expire_days,
        )

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def hash_password(self, plain: str) -> str:
        """Hash a plaintext password with bcrypt.

        Args:
            plain: The plaintext password supplied by the user.

        Returns:
            A bcrypt hash string safe to store in the database.

        Example:
            >>> svc = AuthService("a" * 32)
            >>> h = svc.hash_password("mypassword123")
            >>> h.startswith("$2b$")
            True
        """
        return _pwd_context.hash(plain)

    def verify_password(self, plain: str, hashed: str) -> bool:
        """Verify a plaintext password against a stored bcrypt hash.

        Args:
            plain: The plaintext password supplied by the user.
            hashed: The bcrypt hash retrieved from the database.

        Returns:
            ``True`` if the password matches the hash, ``False`` otherwise.

        Example:
            >>> svc = AuthService("a" * 32)
            >>> h = svc.hash_password("mypassword123")
            >>> svc.verify_password("mypassword123", h)
            True
            >>> svc.verify_password("wrongpassword", h)
            False
        """
        return _pwd_context.verify(plain, hashed)

    # ------------------------------------------------------------------
    # Token creation
    # ------------------------------------------------------------------

    def create_access_token(self, user_id: str, email: str, role: str) -> str:
        """Create a signed JWT access token.

        The payload contains: ``sub`` (user_id), ``email``, ``role``,
        ``type="access"``, ``jti`` (unique token ID), ``iat``, ``exp``.

        Args:
            user_id: UUID string of the authenticated user.
            email: Email address to embed in the token.
            role: User role (``"superuser"`` or ``"general"``).

        Returns:
            A signed JWT string.

        Example:
            >>> svc = AuthService("a" * 32)
            >>> token = svc.create_access_token("uid", "u@x.com", "general")
            >>> isinstance(token, str)
            True
        """
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "sub": user_id,
            "email": email,
            "role": role,
            "type": _ACCESS_TOKEN_TYPE,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=self._access_expire_minutes),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=_ALGORITHM)
        logger.debug("Access token created for user_id=%s", user_id)
        return token

    def create_refresh_token(self, user_id: str) -> str:
        """Create a signed JWT refresh token.

        The payload contains: ``sub`` (user_id), ``type="refresh"``, ``jti``,
        ``iat``, ``exp``.  The ``jti`` is stored in :attr:`_deny_list` on
        logout to prevent reuse.

        Args:
            user_id: UUID string of the authenticated user.

        Returns:
            A signed JWT string.

        Example:
            >>> svc = AuthService("a" * 32)
            >>> token = svc.create_refresh_token("uid")
            >>> isinstance(token, str)
            True
        """
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "sub": user_id,
            "type": _REFRESH_TOKEN_TYPE,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(days=self._refresh_expire_days),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=_ALGORITHM)
        logger.debug("Refresh token created for user_id=%s", user_id)
        return token

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    def decode_token(self, token: str, expected_type: Optional[str] = None) -> Dict[str, Any]:
        """Decode and validate a JWT, raising HTTP 401 on any failure.

        Checks: signature, expiry, and (if *expected_type* supplied) the
        ``type`` claim.  Also rejects tokens whose ``jti`` appears in the
        deny-list.

        Args:
            token: The raw JWT string.
            expected_type: If provided, the decoded ``type`` claim must equal
                this value (e.g. ``"access"`` or ``"refresh"``).

        Returns:
            The decoded payload dict.

        Raises:
            HTTPException: 401 if the token is invalid, expired, revoked, or
                of the wrong type.

        Example:
            >>> svc = AuthService("a" * 32)
            >>> t = svc.create_access_token("uid", "u@x.com", "general")
            >>> p = svc.decode_token(t, expected_type="access")
            >>> p["role"]
            'general'
        """
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[_ALGORITHM])
        except JWTError as exc:
            logger.warning("JWT decode failed: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

        jti = payload.get("jti", "")
        if jti in self._deny_list:
            raise HTTPException(status_code=401, detail="Token has been revoked")

        if expected_type and payload.get("type") != expected_type:
            raise HTTPException(
                status_code=401,
                detail=f"Expected token type '{expected_type}', got '{payload.get('type')}'",
            )

        return payload

    # ------------------------------------------------------------------
    # Deny-list (logout support)
    # ------------------------------------------------------------------

    def revoke_refresh_token(self, token: str) -> None:
        """Add a refresh token's JTI to the in-memory deny-list.

        Called by ``POST /auth/logout``.  Subsequent calls to
        :meth:`decode_token` with this token will return HTTP 401.

        Args:
            token: The raw refresh JWT string to revoke.  If the token cannot
                be decoded (already expired, malformed) the revocation is
                silently skipped.

        Example:
            >>> svc = AuthService("a" * 32)
            >>> t = svc.create_refresh_token("uid")
            >>> svc.revoke_refresh_token(t)
        """
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[_ALGORITHM])
            jti = payload.get("jti", "")
            if jti:
                self._deny_list.add(jti)
                logger.info("Refresh token revoked (jti=%s).", jti)
        except JWTError:
            # Token is already invalid — nothing to revoke.
            logger.debug("revoke_refresh_token: token already invalid, skipping.")

    def is_token_revoked(self, token: str) -> bool:
        """Check whether a token's JTI is in the deny-list.

        Args:
            token: The raw JWT string to check.

        Returns:
            ``True`` if the token has been revoked, ``False`` otherwise.

        Example:
            >>> svc = AuthService("a" * 32)
            >>> t = svc.create_refresh_token("uid")
            >>> svc.is_token_revoked(t)
            False
            >>> svc.revoke_refresh_token(t)
            >>> svc.is_token_revoked(t)
            True
        """
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[_ALGORITHM])
            return payload.get("jti", "") in self._deny_list
        except JWTError:
            return True

    # ------------------------------------------------------------------
    # Password strength validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_password_strength(password: str) -> None:
        """Raise HTTP 400 if *password* does not meet minimum requirements.

        Requirements:
        - At least 8 characters.
        - At least one digit.

        Args:
            password: The plaintext password to validate.

        Raises:
            HTTPException: 400 if the password is too weak.

        Example:
            >>> AuthService.validate_password_strength("abc123def")  # passes
            >>> AuthService.validate_password_strength("abcdefgh")  # doctest: +SKIP
            Traceback (most recent call last):
                ...
            fastapi.HTTPException: 400
        """
        if len(password) < 8:
            raise HTTPException(
                status_code=400, detail="Password must be at least 8 characters."
            )
        if not any(c.isdigit() for c in password):
            raise HTTPException(
                status_code=400, detail="Password must contain at least one digit."
            )
