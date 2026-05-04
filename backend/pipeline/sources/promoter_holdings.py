"""BSE shareholding-pattern source (Sprint 9 Advanced Analytics).

Fetches quarterly promoter holding percentage, pledged
percentage, and quarter-over-quarter change from the BSE
shareholding-pattern public API.  Used by the
``promoter_holdings_quarterly`` scheduled job (AA-4) to
populate ``stocks.promoter_holdings``.

Two-step BSE API workflow:

1. ``getPromoterShareholding`` — returns the latest
   shareholding pattern row for a given BSE scrip code.
2. ``getQtrwiseShareholding`` — returns historical
   quarter-by-quarter rows used to compute QoQ change.

This source is intentionally defensive — BSE serves
through a Cloudflare WAF that can return 403/captcha
responses for bursty traffic.  Failures surface as
:class:`SourceError` with the existing categorisation; the
caller is expected to skip the ticker and continue.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import httpx
import pandas as pd

from backend.pipeline.sources.base import (
    SourceError,
    SourceErrorCategory,
    classify_error,
)

_logger = logging.getLogger(__name__)

# BSE public API.  The host is shared by their web
# frontend; we set a browser-like User-Agent to avoid
# the default-UA Cloudflare block.
_BSE_API_BASE = "https://api.bseindia.com/BseIndiaAPI/api"
_BSE_REFERER = "https://www.bseindia.com/"
_BSE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_TIMEOUT_S = 15.0

_OUT_COLS = [
    "ticker",
    "quarter_end",
    "prom_hld_pct",
    "pledged_pct",
    "chng_qoq",
    "source",
]


class BseShareholdingSource:
    """Async client for BSE shareholding-pattern API.

    Each instance creates its own :class:`httpx.AsyncClient`
    on first use (and closes it via :meth:`aclose`).  Use as
    an async context manager when ingesting many tickers in
    one job:

    .. code-block:: python

        async with BseShareholdingSource() as src:
            for code, ticker in mapping.items():
                df = await src.fetch_quarterly(code, ticker)
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._warm: bool = False

    async def __aenter__(self) -> "BseShareholdingSource":
        self._client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT_S,
            headers={
                "User-Agent": _BSE_USER_AGENT,
                "Referer": _BSE_REFERER,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.bseindia.com",
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

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Return the active client, warming cookies first."""
        if self._client is None:
            await self.__aenter__()
        assert self._client is not None
        if not self._warm:
            try:
                await asyncio.wait_for(
                    self._client.get(_BSE_REFERER),
                    timeout=_DEFAULT_TIMEOUT_S,
                )
            except Exception as exc:
                _logger.warning(
                    "BSE warmup failed: %s",
                    exc,
                )
            self._warm = True
        return self._client

    async def fetch_quarterly(
        self,
        scrip_code: str,
        ticker: str,
    ) -> pd.DataFrame:
        """Fetch quarter-by-quarter promoter holdings.

        Args:
            scrip_code: BSE numeric scrip code as a string
                (e.g. ``"500325"`` for RELIANCE).  Mapping
                from ``stock_master`` ticker → scrip_code
                is the caller's responsibility.
            ticker: Our canonical ticker (``.NS`` form) —
                stamped into the output for downstream
                joins.

        Returns:
            DataFrame with one row per available quarter,
            columns ``ticker, quarter_end, prom_hld_pct,
            pledged_pct, chng_qoq, source``.  Empty when
            BSE returns no data for *scrip_code*.

        Raises:
            SourceError: HTTP timeout, 4xx/5xx response,
                or parse failure.  Cloudflare blocks land
                here as a ``RATE_LIMIT`` category most of
                the time.
        """
        client = await self._ensure_client()
        url = f"{_BSE_API_BASE}/QtrShareholding/w" f"?scripcode={scrip_code}"
        try:
            r = await asyncio.wait_for(
                client.get(url),
                timeout=_DEFAULT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise SourceError(
                SourceErrorCategory.TIMEOUT,
                (
                    f"BSE shareholding fetch timed out "
                    f"for {ticker} (scrip={scrip_code})"
                ),
            )
        except Exception as exc:
            raise SourceError(
                classify_error(exc),
                (
                    f"BSE shareholding fetch failed for "
                    f"{ticker} (scrip={scrip_code}): {exc}"
                ),
                original=exc,
            ) from exc

        if r.status_code != 200:
            raise SourceError(
                (
                    SourceErrorCategory.RATE_LIMIT
                    if r.status_code in (403, 429)
                    else SourceErrorCategory.UNKNOWN
                ),
                (
                    f"BSE shareholding HTTP "
                    f"{r.status_code} for {ticker} "
                    f"(scrip={scrip_code})"
                ),
            )

        try:
            payload = r.json()
        except Exception as exc:
            raise SourceError(
                SourceErrorCategory.PARSE_ERROR,
                f"BSE shareholding non-JSON for {ticker}: " f"{exc}",
                original=exc,
            ) from exc

        return self._normalise(payload, ticker)

    @staticmethod
    def _normalise(
        payload: Any,
        ticker: str,
    ) -> pd.DataFrame:
        """Project BSE response to our schema.

        BSE returns a list of dicts; each row carries the
        quarter end (``QtrId`` / ``EndDate``), promoter %
        (``Promoter`` / ``Total_PromoterAndPromoterGroup``)
        and pledged %.  Field naming varies across vintages
        of the API; we accept several aliases.
        """
        rows: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            rows = payload.get("Table") or []
        elif isinstance(payload, list):
            rows = payload
        if not rows:
            return pd.DataFrame(columns=_OUT_COLS)

        out: list[dict[str, Any]] = []
        for r in rows:
            qtr = r.get("EndDate") or r.get("QtrEnd") or r.get("QuarterEnd")
            try:
                qtr_d = pd.to_datetime(qtr).date()
            except Exception:
                continue
            prom = (
                r.get("Total_PromoterAndPromoterGroup")
                or r.get("Promoter")
                or r.get("PromoterPercentage")
            )
            pledged = r.get("PledgedPercentage") or r.get("Pledged")
            try:
                prom_f = float(prom) if prom is not None else None
                pledged_f = float(pledged) if pledged is not None else None
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "ticker": ticker,
                    "quarter_end": qtr_d,
                    "prom_hld_pct": prom_f,
                    "pledged_pct": pledged_f,
                    "source": "bse",
                }
            )

        if not out:
            return pd.DataFrame(columns=_OUT_COLS)

        df = pd.DataFrame(out).sort_values("quarter_end")
        # QoQ change in promoter holding %.
        df["chng_qoq"] = df["prom_hld_pct"].diff()
        return df[_OUT_COLS].reset_index(drop=True)


def latest_quarter_end(today: date | None = None) -> date:
    """Return the last calendar-quarter-end on or before *today*.

    BSE shareholding patterns are filed against quarter
    ends (Mar 31 / Jun 30 / Sep 30 / Dec 31).  Filings
    typically lag by ~21 days from the quarter end.

    Args:
        today: Reference date; defaults to today.

    Returns:
        ``datetime.date`` for the most recent quarter end.
    """
    if today is None:
        today = date.today()
    if today.month >= 12:
        return date(today.year, 12, 31)
    if today.month >= 9:
        return date(today.year, 9, 30)
    if today.month >= 6:
        return date(today.year, 6, 30)
    if today.month >= 3:
        return date(today.year, 3, 31)
    return date(today.year - 1, 12, 31)
