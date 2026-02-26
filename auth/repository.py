"""Iceberg-backed repository for user records and audit log entries.

This module provides :class:`IcebergUserRepository`, the single point of access
for reading and writing to the ``auth.users`` and ``auth.audit_log`` Iceberg
tables.  All CRUD operations are performed through this class — no code outside
this module should interact with the Iceberg tables directly.

Write semantics
---------------
- **Create** — appends a new single-row PyArrow ``RecordBatch``.
- **Update** — reads the full table as a pandas ``DataFrame``, mutates the
  target row in-place, then overwrites the table (copy-on-write).  Acceptable
  for the expected user-table size (< 10 000 rows).
- **Delete** — soft delete via ``is_active = False``; the row is never
  physically removed from the table.
- **Audit log** — append-only; rows are never updated or deleted.

Usage::

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    from auth.repository import IcebergUserRepository

    repo = IcebergUserRepository()
    user = repo.get_by_email("admin@example.com")
"""

import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pyarrow as pa

# Module-level logger (mutable, but safe for use across the module)
_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table identifiers — must match auth/create_tables.py
# ---------------------------------------------------------------------------
_NAMESPACE = "auth"
_USERS_TABLE = f"{_NAMESPACE}.users"
_AUDIT_LOG_TABLE = f"{_NAMESPACE}.audit_log"

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
# PyIceberg TimestampType maps to pa.timestamp("us") — microsecond precision,
# no explicit timezone.  We always treat stored values as UTC.
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return the current UTC datetime as a *naive* datetime (no tzinfo).

    PyArrow ``pa.timestamp('us')`` expects naive datetime values when the
    Iceberg column is ``TimestampType`` (no timezone).  Internally we always
    treat these as UTC.

    Returns:
        A naive :class:`datetime.datetime` representing the current UTC time.
    """
    return datetime.utcnow()


def _to_ts(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise a datetime to a naive UTC datetime suitable for storage.

    PyArrow ``pa.timestamp('us')`` requires naive datetimes.  If *dt* carries
    timezone information it is first converted to UTC then the tzinfo is
    stripped.

    Args:
        dt: Any :class:`datetime.datetime`, or ``None``.

    Returns:
        A naive :class:`datetime.datetime` in UTC, or ``None``.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _from_ts(val: Any) -> Optional[datetime]:
    """Convert a raw timestamp value from a PyArrow / pandas scan to datetime.

    PyArrow returns ``pa.timestamp('us')`` columns as
    :class:`pandas.Timestamp` objects (when read via ``to_pylist()`` they
    arrive as :class:`datetime.datetime`).  We attach UTC tzinfo so callers
    always receive timezone-aware datetimes.

    Args:
        val: A :class:`datetime.datetime`, :class:`pandas.Timestamp`, ``None``,
            or a float ``NaN`` produced by pandas for null values.

    Returns:
        A timezone-aware :class:`datetime.datetime` in UTC, or ``None``.
    """
    if val is None:
        return None
    # pandas represents nullable int/timestamp NaN as float NaN
    if isinstance(val, float) and math.isnan(val):
        return None
    if hasattr(val, "to_pydatetime"):
        val = val.to_pydatetime()
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    return None


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
# pa.timestamp("us") matches PyIceberg's TimestampType (microseconds, no tz).
# ---------------------------------------------------------------------------

# Immutable schema constant for the users table
_TS = pa.timestamp("us")

# Immutable schema constant for the users table
_USERS_PA_SCHEMA = pa.schema(
    [
        pa.field("user_id", pa.string(), nullable=False),
        pa.field("email", pa.string(), nullable=False),
        pa.field("hashed_password", pa.string(), nullable=False),
        pa.field("full_name", pa.string(), nullable=False),
        pa.field("role", pa.string(), nullable=False),
        pa.field("is_active", pa.bool_(), nullable=False),
        pa.field("created_at", _TS, nullable=False),
        pa.field("updated_at", _TS, nullable=False),
        pa.field("last_login_at", _TS, nullable=True),
        pa.field("password_reset_token", pa.string(), nullable=True),
        pa.field("password_reset_expiry", _TS, nullable=True),
        # SSO columns — nullable for email-only accounts.
        pa.field("oauth_provider", pa.string(), nullable=True),
        pa.field("oauth_sub", pa.string(), nullable=True),
        pa.field("profile_picture_url", pa.string(), nullable=True),
    ]
)

# Immutable schema constant for the audit log table
_AUDIT_PA_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("actor_user_id", pa.string(), nullable=False),
        pa.field("target_user_id", pa.string(), nullable=False),
        pa.field("event_timestamp", _TS, nullable=False),
        pa.field("metadata", pa.string(), nullable=True),
    ]
)

_USER_TS_COLS = ("created_at", "updated_at", "last_login_at", "password_reset_expiry")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert an Iceberg scan row (or pandas Series) to a plain Python dict.

    Timestamp columns are converted to timezone-aware UTC
    :class:`datetime.datetime` objects via :func:`_from_ts`.

    Args:
        row: A mapping-like object from ``to_pylist()`` or a pandas ``Series``.

    Returns:
        A plain :class:`dict` with Python-native values.
    """
    d: Dict[str, Any] = dict(row)
    for ts_col in _USER_TS_COLS:
        if ts_col in d:
            d[ts_col] = _from_ts(d[ts_col])
    return d


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class IcebergUserRepository:
    """CRUD repository for the ``auth.users`` and ``auth.audit_log`` Iceberg tables.

    This class is the single access point for all user and audit-log
    persistence.  It owns a lazy-loaded reference to the Iceberg catalog and
    surfaces simple Python-dict-in / Python-dict-out methods so callers never
    need to interact with PyArrow or PyIceberg directly.

    The catalog is loaded from ``.pyiceberg.yaml`` (project root or ``$HOME``)
    on first access.  The working directory is changed to the project root at
    construction time so that relative paths in ``.pyiceberg.yaml`` resolve
    correctly.

    Attributes:
        _catalog: Lazily loaded Iceberg catalog instance.
        _project_root: Absolute path to the project root directory.
    """

    def __init__(self) -> None:
        """Initialise the repository and resolve the project root.

        The working directory is set to the project root so that the relative
        ``sqlite:///data/iceberg/catalog.db`` URI in ``.pyiceberg.yaml``
        resolves correctly regardless of where Python is invoked from.
        """
        self._catalog = None
        self._project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.chdir(self._project_root)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_catalog(self):
        """Return the Iceberg catalog, loading it on first access.

        Returns:
            A :class:`pyiceberg.catalog.sql.SqlCatalog` instance.

        Raises:
            RuntimeError: If the catalog cannot be loaded (e.g. missing
                ``.pyiceberg.yaml`` or unreadable warehouse directory).
        """
        if self._catalog is None:
            from pyiceberg.catalog import load_catalog

            try:
                self._catalog = load_catalog("local")
                _logger.debug("Iceberg catalog loaded.")
            except Exception as exc:
                raise RuntimeError(
                    "Failed to load Iceberg catalog. "
                    "Check that .pyiceberg.yaml exists and data/iceberg/ is writable."
                ) from exc
        return self._catalog

    def _users_table(self):
        """Return the open ``auth.users`` Iceberg table.

        Returns:
            The ``auth.users`` :class:`pyiceberg.table.Table`.
        """
        return self._get_catalog().load_table(_USERS_TABLE)

    def _audit_table(self):
        """Return the open ``auth.audit_log`` Iceberg table.

        Returns:
            The ``auth.audit_log`` :class:`pyiceberg.table.Table`.
        """
        return self._get_catalog().load_table(_AUDIT_LOG_TABLE)

    def _scan_all_users(self) -> List[Dict[str, Any]]:
        """Read every row from ``auth.users`` and return as a list of dicts.

        Returns:
            A list of user dicts; empty list if the table has no rows.
        """
        table = self._users_table()
        scan = table.scan()
        arrow_table = scan.to_arrow()
        return [_row_to_dict(row) for row in arrow_table.to_pylist()]

    # ------------------------------------------------------------------
    # User reads
    # ------------------------------------------------------------------

    def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Fetch a single user by email address.

        Args:
            email: The email address to search for.

        Returns:
            A user dict if found, otherwise ``None``.

        Example:
            >>> repo = IcebergUserRepository()
            >>> user = repo.get_by_email("admin@example.com")
            >>> user is None or isinstance(user, dict)
            True
        """
        table = self._users_table()
        try:
            from pyiceberg.expressions import EqualTo

            arrow = table.scan(row_filter=EqualTo("email", email)).to_arrow()
            rows = arrow.to_pylist()
            if not rows:
                return None
            return _row_to_dict(rows[0])
        except Exception as exc:
            _logger.warning("get_by_email scan failed, falling back to full scan: %s", exc)
            for row in self._scan_all_users():
                if row.get("email") == email:
                    return row
            return None

    def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single user by UUID.

        Args:
            user_id: The UUID string of the user to retrieve.

        Returns:
            A user dict if found, otherwise ``None``.

        Example:
            >>> repo = IcebergUserRepository()
            >>> user = repo.get_by_id("00000000-0000-0000-0000-000000000000")
            >>> user is None or isinstance(user, dict)
            True
        """
        table = self._users_table()
        try:
            from pyiceberg.expressions import EqualTo

            arrow = table.scan(row_filter=EqualTo("user_id", user_id)).to_arrow()
            rows = arrow.to_pylist()
            if not rows:
                return None
            return _row_to_dict(rows[0])
        except Exception as exc:
            _logger.warning("get_by_id scan failed, falling back to full scan: %s", exc)
            for row in self._scan_all_users():
                if row.get("user_id") == user_id:
                    return row
            return None

    def list_all(self) -> List[Dict[str, Any]]:
        """Return all users from the ``auth.users`` table.

        Returns:
            A list of user dicts (may be empty).

        Example:
            >>> repo = IcebergUserRepository()
            >>> users = repo.list_all()
            >>> isinstance(users, list)
            True
        """
        return self._scan_all_users()

    # ------------------------------------------------------------------
    # User writes
    # ------------------------------------------------------------------

    def create(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Append a new user row to the ``auth.users`` table.

        The caller must supply all required fields.  ``user_id``,
        ``created_at``, and ``updated_at`` are generated automatically if not
        present in *user_data*.

        Args:
            user_data: A dict with at minimum ``email``, ``hashed_password``,
                ``full_name``, and ``role``.  Optional fields default to
                sensible values.

        Returns:
            The full user dict as stored, including generated fields.

        Raises:
            ValueError: If a user with the same email already exists.

        Example:
            >>> repo = IcebergUserRepository()
            >>> # repo.create({...})  # doctest: +SKIP
        """
        if self.get_by_email(user_data["email"]) is not None:
            raise ValueError(f"User with email '{user_data['email']}' already exists.")

        now = _now_utc()
        row = {
            "user_id": user_data.get("user_id", str(uuid.uuid4())),
            "email": user_data["email"],
            "hashed_password": user_data["hashed_password"],
            "full_name": user_data["full_name"],
            "role": user_data.get("role", "general"),
            "is_active": user_data.get("is_active", True),
            "created_at": _to_ts(user_data.get("created_at", now)),
            "updated_at": _to_ts(user_data.get("updated_at", now)),
            "last_login_at": _to_ts(user_data.get("last_login_at")),
            "password_reset_token": user_data.get("password_reset_token"),
            "password_reset_expiry": _to_ts(user_data.get("password_reset_expiry")),
            # SSO fields — None for email-only accounts.
            "oauth_provider": user_data.get("oauth_provider"),
            "oauth_sub": user_data.get("oauth_sub"),
            "profile_picture_url": user_data.get("profile_picture_url"),
        }

        arrow_table = pa.table(
            {k: [v] for k, v in row.items()},
            schema=_USERS_PA_SCHEMA,
        )
        table = self._users_table()
        table.append(arrow_table)
        _logger.info("Created user user_id=%s email=%s", row["user_id"], row["email"])

        # Return Python-native dict with timezone-aware datetime objects
        stored = dict(row)
        for ts_col in _USER_TS_COLS:
            stored[ts_col] = _from_ts(stored[ts_col])
        return stored

    def update(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Apply *updates* to the user identified by *user_id*.

        Uses copy-on-write semantics: reads the full table, mutates the target
        row, then overwrites the table.  The ``updated_at`` field is always
        refreshed to the current UTC time.

        Args:
            user_id: UUID string of the user to update.
            updates: Dict of fields to overwrite.  Any key valid in the users
                schema may be supplied (except ``user_id`` and ``created_at``
                which are immutable).

        Returns:
            The full updated user dict.

        Raises:
            ValueError: If no user with the given *user_id* exists.

        Example:
            >>> repo = IcebergUserRepository()
            >>> # repo.update("some-uuid", {"full_name": "New Name"})  # doctest: +SKIP
        """
        import pandas as pd

        table = self._users_table()
        arrow_table = table.scan().to_arrow()
        df: pd.DataFrame = arrow_table.to_pandas()

        mask = df["user_id"] == user_id
        if not mask.any():
            raise ValueError(f"User '{user_id}' not found.")

        # Apply allowed updates (immutable fields are silently skipped)
        immutable = {"user_id", "created_at"}
        for field, value in updates.items():
            if field in immutable:
                continue
            if field in ("last_login_at", "password_reset_expiry"):
                df.loc[mask, field] = _to_ts(value)
            else:
                df.loc[mask, field] = value

        # Always refresh updated_at
        df.loc[mask, "updated_at"] = _to_ts(_now_utc())

        # Overwrite table (copy-on-write)
        new_arrow = pa.Table.from_pandas(df, schema=_USERS_PA_SCHEMA, preserve_index=False)
        table.overwrite(new_arrow)
        _logger.info("Updated user user_id=%s fields=%s", user_id, list(updates.keys()))

        updated_row = df[mask].iloc[0].to_dict()
        return _row_to_dict(updated_row)

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------

    def get_by_oauth_sub(self, provider: str, oauth_sub: str) -> Optional[Dict[str, Any]]:
        """Fetch a user matched by OAuth provider + provider-specific subject ID.

        Args:
            provider: The OAuth provider name, e.g. ``"google"`` or
                ``"facebook"``.
            oauth_sub: The provider's unique user ID (``sub`` claim from
                Google's ``id_token``, or Facebook Graph API ``id``).

        Returns:
            A user dict if a matching account is found, otherwise ``None``.

        Example:
            >>> repo = IcebergUserRepository()
            >>> user = repo.get_by_oauth_sub("google", "1234567890")
            >>> user is None or isinstance(user, dict)
            True
        """
        for row in self._scan_all_users():
            if row.get("oauth_provider") == provider and row.get("oauth_sub") == oauth_sub:
                return row
        return None

    def get_or_create_by_oauth(
        self,
        provider: str,
        oauth_sub: str,
        email: str,
        full_name: str,
        picture_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return an existing user or create a new SSO-only account.

        Lookup order:
        1. Match on ``(oauth_sub, oauth_provider)`` — returning SSO user.
        2. Match on ``email`` — existing email account; link the OAuth
           provider to it on first SSO login.
        3. No match — create a new account with a sentinel password hash
           that always fails bcrypt verification.

        The ``profile_picture_url`` and ``last_login_at`` are refreshed on
        every successful SSO login regardless of which lookup branch matched.

        Args:
            provider: OAuth provider name (``"google"`` or ``"facebook"``).
            oauth_sub: Provider-specific unique user ID.
            email: Email address returned by the provider.
            full_name: Display name returned by the provider.
            picture_url: Avatar URL from the provider, or ``None``.

        Returns:
            The full user dict after upsert.

        Example:
            >>> repo = IcebergUserRepository()
            >>> # repo.get_or_create_by_oauth("google", "sub", "a@b.com", "A B")
        """
        import secrets as _secrets

        now = _now_utc()

        # 1. Match on (oauth_sub, oauth_provider) — returning user.
        existing = self.get_by_oauth_sub(provider, oauth_sub)
        if existing is not None:
            self.update(
                existing["user_id"],
                {
                    "profile_picture_url": picture_url,
                    "last_login_at": now,
                },
            )
            refreshed = self.get_by_id(existing["user_id"])
            return refreshed or existing

        # 2. Match on email — link OAuth to an existing email account.
        by_email = self.get_by_email(email)
        if by_email is not None:
            self.update(
                by_email["user_id"],
                {
                    "oauth_provider": provider,
                    "oauth_sub": oauth_sub,
                    "profile_picture_url": picture_url,
                    "last_login_at": now,
                },
            )
            refreshed = self.get_by_id(by_email["user_id"])
            return refreshed or by_email

        # 3. No match — create a new SSO-only account.
        sentinel = f"!sso_only_{_secrets.token_hex(32)}"
        new_user = self.create(
            {
                "email": email,
                "hashed_password": sentinel,
                "full_name": full_name,
                "role": "general",
                "oauth_provider": provider,
                "oauth_sub": oauth_sub,
                "profile_picture_url": picture_url,
            }
        )
        _logger.info(
            "Created SSO account: user_id=%s provider=%s", new_user["user_id"], provider
        )
        return new_user

    def delete(self, user_id: str) -> None:
        """Soft-delete a user by setting ``is_active = False``.

        The row is never physically removed from the Iceberg table.  Hard
        deletes can be implemented later via Iceberg row-level deletes
        (PyIceberg >= 0.7).

        Args:
            user_id: UUID string of the user to deactivate.

        Raises:
            ValueError: If no user with the given *user_id* exists.

        Example:
            >>> repo = IcebergUserRepository()
            >>> # repo.delete("some-uuid")  # doctest: +SKIP
        """
        self.update(user_id, {"is_active": False})
        _logger.info("Soft-deleted user user_id=%s", user_id)

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def append_audit_event(
        self,
        event_type: str,
        actor_user_id: str,
        target_user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an immutable event row to the ``auth.audit_log`` table.

        Args:
            event_type: One of ``USER_CREATED``, ``USER_UPDATED``,
                ``USER_DELETED``, ``LOGIN``, ``PASSWORD_RESET``.
            actor_user_id: UUID of the user who performed the action.
            target_user_id: UUID of the user who was affected.
            metadata: Optional dict of extra context (serialised to JSON).

        Example:
            >>> repo = IcebergUserRepository()
            >>> # repo.append_audit_event("LOGIN", "uid", "uid")  # doctest: +SKIP
        """
        row = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "target_user_id": target_user_id,
            "event_timestamp": _to_ts(_now_utc()),
            "metadata": json.dumps(metadata) if metadata else None,
        }
        arrow_table = pa.table(
            {k: [v] for k, v in row.items()},
            schema=_AUDIT_PA_SCHEMA,
        )
        self._audit_table().append(arrow_table)
        _logger.debug(
            "Audit event type=%s actor=%s target=%s",
            event_type,
            actor_user_id,
            target_user_id,
        )

    def list_audit_events(self) -> List[Dict[str, Any]]:
        """Return all audit log events, sorted newest-first.

        Returns:
            A list of audit event dicts.

        Example:
            >>> repo = IcebergUserRepository()
            >>> events = repo.list_audit_events()
            >>> isinstance(events, list)
            True
        """
        table = self._audit_table()
        arrow = table.scan().to_arrow()
        rows = arrow.to_pylist()
        result = []
        for row in rows:
            d = dict(row)
            d["event_timestamp"] = _from_ts(d.get("event_timestamp"))
            result.append(d)
        result.sort(
            key=lambda r: r.get("event_timestamp")
            or datetime(1970, 1, 1, tzinfo=timezone.utc),
            reverse=True,
        )
        return result