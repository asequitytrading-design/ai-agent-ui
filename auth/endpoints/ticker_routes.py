"""User ticker management endpoints.

Provides REST endpoints for linking, unlinking, and listing
ticker symbols associated with the authenticated user.

Endpoints
---------
- ``GET /users/me/tickers`` — list linked tickers
- ``POST /users/me/tickers`` — link a new ticker
- ``DELETE /users/me/tickers/{ticker}`` — unlink a ticker
"""

import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# validation.py is in backend/ which is on sys.path
from validation import validate_ticker

import auth.endpoints.helpers as _helpers
from auth.dependencies import get_current_user
from auth.models import UserContext

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users/me",
    tags=["tickers"],
)


class LinkTickerRequest(BaseModel):
    """Request body for linking a ticker to the user.

    Attributes:
        ticker: Uppercase ticker symbol (e.g. ``AAPL``).
        source: How the link was created. Defaults
            to ``"manual"``.
    """

    ticker: str = Field(
        ...,
        description="Ticker symbol to link.",
    )
    source: str = Field(
        default="manual",
        description=("How the link was created " "(e.g. 'manual', 'chat')."),
    )


@router.get("/tickers")
def get_user_tickers(
    user: UserContext = Depends(get_current_user),
) -> Dict[str, List[str]]:
    """Return the current user's linked tickers.

    Args:
        user: Authenticated user context from JWT.

    Returns:
        A dict ``{"tickers": ["AAPL", ...]}`` with
        sorted ticker symbols.
    """
    repo = _helpers._get_repo()
    tickers = repo.get_user_tickers(user.user_id)
    _logger.debug(
        "Listed %d tickers for user_id=%s",
        len(tickers),
        user.user_id,
    )
    return {"tickers": tickers}


@router.post("/tickers")
def link_ticker(
    body: LinkTickerRequest,
    user: UserContext = Depends(get_current_user),
) -> Dict[str, object]:
    """Link a ticker symbol to the current user.

    Validates the ticker format, normalises to uppercase,
    and delegates to the repository.

    Args:
        body: Request body with ``ticker`` and optional
            ``source``.
        user: Authenticated user context from JWT.

    Returns:
        ``{"linked": true, "ticker": "AAPL"}`` on success,
        or ``{"linked": false, "detail": "already linked"}``
        if the ticker was already linked.

    Raises:
        HTTPException: 422 if the ticker format is invalid.
    """
    err = validate_ticker(body.ticker)
    if err:
        raise HTTPException(
            status_code=422,
            detail=err,
        )

    ticker = body.ticker.upper().strip()
    repo = _helpers._get_repo()
    try:
        linked = repo.link_ticker(
            user.user_id,
            ticker,
            body.source,
        )
    except RuntimeError as exc:
        _logger.error("link_ticker failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Ticker storage unavailable."
                " Run: python auth/create_tables.py"
            ),
        ) from exc

    if linked:
        _logger.info(
            "User %s linked ticker=%s source=%s",
            user.user_id,
            ticker,
            body.source,
        )
        return {"linked": True, "ticker": ticker}

    return {
        "linked": False,
        "detail": "already linked",
    }


@router.delete("/tickers/{ticker}")
def unlink_ticker(
    ticker: str,
    user: UserContext = Depends(get_current_user),
) -> Dict[str, str]:
    """Unlink a ticker symbol from the current user.

    Args:
        ticker: Ticker symbol from the URL path.
        user: Authenticated user context from JWT.

    Returns:
        ``{"detail": "unlinked"}`` on success.

    Raises:
        HTTPException: 404 if the ticker was not linked.
    """
    normalised = ticker.upper().strip()
    repo = _helpers._get_repo()
    try:
        removed = repo.unlink_ticker(
            user.user_id,
            normalised,
        )
    except RuntimeError as exc:
        _logger.error("unlink_ticker failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Ticker storage unavailable."
                " Run: python auth/create_tables.py"
            ),
        ) from exc

    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker '{normalised}' not linked",
        )

    _logger.info(
        "User %s unlinked ticker=%s",
        user.user_id,
        normalised,
    )
    return {"detail": "unlinked"}


# ---------------------------------------------------------------
# User Preferences (localStorage + Redis sync)
# ---------------------------------------------------------------

_PREFS_TTL = 7 * 86400  # 7 days sliding TTL


@router.get("/preferences")
def get_preferences(
    user: UserContext = Depends(get_current_user),
) -> Dict:
    """Return stored preferences for the current user.

    Reads from Redis with key ``prefs:{user_id}``.
    Returns empty dict if no preferences are stored.
    Extends the sliding TTL on every read.
    """
    import json

    try:
        from cache import get_cache
    except ImportError:
        return {}

    cache = get_cache()
    key = f"prefs:{user.user_id}"
    raw = cache.get(key)
    if raw is None:
        return {}
    try:
        prefs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    # Extend sliding TTL on read
    cache.set(key, raw, _PREFS_TTL)
    return prefs


class PreferencesBody(BaseModel):
    """Full preferences payload from the frontend."""

    chart: Dict | None = None
    dashboard: Dict | None = None
    insights: Dict | None = None
    admin: Dict | None = None
    navigation: Dict | None = None
    last_login: str | None = None


@router.put("/preferences")
def put_preferences(
    body: PreferencesBody,
    user: UserContext = Depends(get_current_user),
) -> Dict[str, str]:
    """Upsert preferences for the current user.

    Merges with existing preferences so partial
    updates are supported.  Sets a sliding 7-day TTL.
    """
    import json

    try:
        from cache import get_cache
    except ImportError:
        return {"detail": "cache unavailable"}

    cache = get_cache()
    key = f"prefs:{user.user_id}"

    # Merge with existing
    existing: dict = {}
    raw = cache.get(key)
    if raw:
        try:
            existing = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

    incoming = body.model_dump(exclude_none=True)
    for section, values in incoming.items():
        if isinstance(values, dict) and isinstance(
            existing.get(section), dict
        ):
            existing[section].update(values)
        else:
            existing[section] = values

    cache.set(
        key, json.dumps(existing), _PREFS_TTL,
    )
    _logger.info(
        "Preferences saved for user %s",
        user.user_id,
    )
    return {"detail": "saved"}
