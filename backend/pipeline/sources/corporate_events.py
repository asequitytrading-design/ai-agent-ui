"""NSE corporate-events source (Sprint 9 Advanced Analytics).

Fetches recent corporate events — board meetings,
financial-results announcements, dividends, stock splits,
and other actions — from the public NSE corporate APIs.
Used by the ``corporate_events_daily`` scheduled job
(AA-4) to populate ``stocks.corporate_events``.

NSE serves the corporate APIs behind Cloudflare; the
default ``python-requests`` User-Agent gets an immediate
403.  This module performs a one-shot cookie warmup against
``https://www.nseindia.com/`` before hitting the API
endpoints, mirroring the standard NSE-scraping pattern.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import httpx
import pandas as pd

from backend.pipeline.sources.base import (
    SourceError,
    SourceErrorCategory,
    classify_error,
)

_logger = logging.getLogger(__name__)

_NSE_HOME = "https://www.nseindia.com"
_NSE_API = f"{_NSE_HOME}/api"
_NSE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_TIMEOUT_S = 20.0

# Mapping from NSE response payload type → our
# ``event_type`` enum.  Keep the LHS lowercased — we
# normalise on read.
_EVENT_TYPE_MAP = {
    "board meeting": "BOARD_MEETING",
    "board meetings": "BOARD_MEETING",
    "corporate action": "CORPORATE_ACTION",
    "corporate actions": "CORPORATE_ACTION",
    "dividend": "DIVIDEND",
    "stock split": "STOCK_SPLIT",
    "split": "STOCK_SPLIT",
    "financial results": "FINANCIAL_RESULTS",
    "results": "FINANCIAL_RESULTS",
    "announcement": "ANNOUNCEMENT",
}

_OUT_COLS = ["ticker", "event_date", "event_type", "event_label"]


class NseCorporateEventsSource:
    """Async client for NSE corporate-events APIs.

    Performs cookie warmup once per session.  Use as an
    async context manager.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._warm: bool = False

    async def __aenter__(self) -> "NseCorporateEventsSource":
        self._client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT_S,
            headers={
                "User-Agent": _NSE_USER_AGENT,
                "Accept": ("application/json, text/plain, */*"),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": _NSE_HOME + "/",
            },
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._warm = False

    async def _ensure_warm(self) -> httpx.AsyncClient:
        """Fetch the NSE homepage once to seed cookies."""
        if self._client is None:
            await self.__aenter__()
        assert self._client is not None
        if self._warm:
            return self._client
        try:
            r = await asyncio.wait_for(
                self._client.get(_NSE_HOME + "/"),
                timeout=_DEFAULT_TIMEOUT_S,
            )
            if r.status_code == 200:
                self._warm = True
            else:
                _logger.warning(
                    "NSE warmup got HTTP %d",
                    r.status_code,
                )
        except Exception as exc:
            _logger.warning("NSE warmup failed: %s", exc)
        return self._client

    async def fetch_recent(
        self,
        days: int = 7,
        index: str = "equities",
    ) -> pd.DataFrame:
        """Fetch corporate events for the last *days* days.

        Pulls the NSE corporate-actions feed; that endpoint
        returns dividends + stock splits + bonus issues +
        rights issues for all listed equities.  For board
        meetings + financial-results announcements use
        :meth:`fetch_board_meetings`.

        Args:
            days: Lookback window (calendar days).  Default
                7 — covers a full trading week.
            index: NSE index family — ``"equities"`` is
                the universe of all listed stocks.

        Returns:
            DataFrame with columns ``ticker, event_date,
            event_type, event_label``.  ``ticker`` is in
            ``.NS`` form to match our convention.

        Raises:
            SourceError: HTTP / parse failures.
        """
        client = await self._ensure_warm()
        end_d = date.today()
        start_d = end_d - timedelta(days=days)
        from_str = start_d.strftime("%d-%m-%Y")
        to_str = end_d.strftime("%d-%m-%Y")
        url = (
            f"{_NSE_API}/corporates-corporateActions"
            f"?index={index}"
            f"&from_date={from_str}"
            f"&to_date={to_str}"
        )
        return await self._fetch_json_to_df(
            client,
            url,
            "corporate-actions",
        )

    async def fetch_board_meetings(
        self,
        days: int = 7,
        index: str = "equities",
    ) -> pd.DataFrame:
        """Fetch upcoming + recent board meetings.

        Board meetings carry the ``purpose`` field which
        usually contains ``"Financial Results"`` for
        quarterly result announcements — the most
        actionable event for advanced-analytics users.

        Args:
            days: Lookback window in days.
            index: NSE index family.

        Returns:
            DataFrame matching :meth:`fetch_recent`'s shape.

        Raises:
            SourceError: HTTP / parse failures.
        """
        client = await self._ensure_warm()
        end_d = date.today()
        start_d = end_d - timedelta(days=days)
        from_str = start_d.strftime("%d-%m-%Y")
        to_str = end_d.strftime("%d-%m-%Y")
        url = (
            f"{_NSE_API}/corporate-board-meetings"
            f"?index={index}"
            f"&from_date={from_str}"
            f"&to_date={to_str}"
        )
        return await self._fetch_json_to_df(
            client,
            url,
            "board-meetings",
        )

    async def _fetch_json_to_df(
        self,
        client: httpx.AsyncClient,
        url: str,
        feed: str,
    ) -> pd.DataFrame:
        """Hit *url*, parse JSON, normalise to our schema."""
        try:
            r = await asyncio.wait_for(
                client.get(url),
                timeout=_DEFAULT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise SourceError(
                SourceErrorCategory.TIMEOUT,
                f"NSE {feed} fetch timed out",
            )
        except Exception as exc:
            raise SourceError(
                classify_error(exc),
                f"NSE {feed} fetch failed: {exc}",
                original=exc,
            ) from exc

        if r.status_code != 200:
            raise SourceError(
                (
                    SourceErrorCategory.RATE_LIMIT
                    if r.status_code in (403, 429)
                    else SourceErrorCategory.UNKNOWN
                ),
                f"NSE {feed} HTTP {r.status_code}",
            )

        try:
            payload = r.json()
        except Exception as exc:
            raise SourceError(
                SourceErrorCategory.PARSE_ERROR,
                f"NSE {feed} non-JSON response: {exc}",
                original=exc,
            ) from exc

        return self._normalise(payload, feed)

    @staticmethod
    def _normalise(
        payload: Any,
        feed: str,
    ) -> pd.DataFrame:
        """Project NSE response → our event schema.

        NSE returns either a top-level list or a dict with
        a ``data`` field.  We accept both.  Symbol field
        is ``symbol`` (corporate-actions) or ``Symbol``
        (board-meetings, with title-case).  Date field is
        ``exDate`` / ``recDate`` / ``meetingDate`` /
        ``bm_date`` depending on feed.
        """
        rows: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("rows") or []
        elif isinstance(payload, list):
            rows = payload
        if not rows:
            return pd.DataFrame(columns=_OUT_COLS)

        out: list[dict[str, Any]] = []
        for r in rows:
            sym = r.get("symbol") or r.get("Symbol") or r.get("scrip")
            if not sym:
                continue
            ticker = f"{str(sym).strip().upper()}.NS"
            d_raw = (
                r.get("exDate")
                or r.get("ex_date")
                or r.get("recDate")
                or r.get("meetingDate")
                or r.get("bm_date")
                or r.get("BoardMeetingDate")
            )
            try:
                d_parsed = pd.to_datetime(
                    d_raw,
                    dayfirst=True,
                ).date()
            except Exception:
                continue
            label = (
                r.get("subject")
                or r.get("purpose")
                or r.get("bm_purpose")
                or r.get("description")
                or r.get("series")
                or feed
            )
            label_str = str(label).strip()
            etype = _EVENT_TYPE_MAP.get(
                label_str.lower(),
                (
                    "BOARD_MEETING"
                    if feed == "board-meetings"
                    else "CORPORATE_ACTION"
                ),
            )
            # Common keyword detection inside free-text
            # labels (e.g. "Quarterly Results") to refine
            # the bucket.
            label_l = label_str.lower()
            if "result" in label_l:
                etype = "FINANCIAL_RESULTS"
            elif "split" in label_l:
                etype = "STOCK_SPLIT"
            elif "dividend" in label_l:
                etype = "DIVIDEND"
            out.append(
                {
                    "ticker": ticker,
                    "event_date": d_parsed,
                    "event_type": etype,
                    "event_label": label_str[:200],
                }
            )

        if not out:
            return pd.DataFrame(columns=_OUT_COLS)
        return (
            pd.DataFrame(out)
            .drop_duplicates(
                subset=["ticker", "event_date", "event_type"],
            )
            .sort_values(["event_date", "ticker"])
            .reset_index(drop=True)
        )
