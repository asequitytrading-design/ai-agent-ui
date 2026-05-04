"""NSE bhavcopy delivery ingestion (Sprint 9 Advanced Analytics).

Single-day ingest: fetches NSE full bhavcopy CSV via
``jugaad-data`` (one HTTP call returning the entire
exchange's price + volume + delivery for the trading day),
projects to the ``stocks.nse_delivery`` schema, and writes
in one Iceberg commit per day.

Multi-day backfill: iterates the date range sequentially,
skipping weekends, with a 1-second cadence between days to
keep NSE rate-limiting happy.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta

from backend.pipeline.sources.base import SourceError
from backend.pipeline.sources.nse import NseSource

_logger = logging.getLogger(__name__)

# Inter-day delay during backfill — gentle on NSE.
_BACKFILL_INTER_DAY_SLEEP_S = 1.0


async def run_bhavcopy(d: date) -> dict:
    """Fetch + ingest NSE bhavcopy for a single trading day.

    Idempotent: a re-run on the same date replaces the
    prior rows for that date (scoped pre-delete inside
    :meth:`StockRepository.insert_nse_delivery`).

    Args:
        d: Trading date to ingest.

    Returns:
        Summary dict with keys ``date`` (str),
        ``status`` (``"ok"`` | ``"skipped"`` | ``"failed"``),
        ``rows`` (int), and optional ``error`` (str) when
        the fetch failed.  Holidays / weekends typically
        return an empty body and surface as
        ``status="skipped"``.
    """
    src = NseSource()
    t0 = time.monotonic()
    try:
        df = await src.fetch_bhavcopy(d)
    except SourceError as exc:
        _logger.warning(
            "Bhavcopy fetch failed for %s: %s",
            d,
            exc,
        )
        return {
            "date": str(d),
            "status": "failed",
            "rows": 0,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 — surface root cause
        _logger.exception(
            "Unexpected error fetching bhavcopy for %s",
            d,
        )
        return {
            "date": str(d),
            "status": "failed",
            "rows": 0,
            "error": str(exc),
        }

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if df.empty:
        _logger.info(
            "No bhavcopy rows for %s " "(weekend or market holiday) — %dms",
            d,
            elapsed_ms,
        )
        return {"date": str(d), "status": "skipped", "rows": 0}

    _logger.info(
        "Bhavcopy fetched %d rows for %s in %dms",
        len(df),
        d,
        elapsed_ms,
    )

    # Bulk write: one Iceberg commit per day.
    from backend.tools._stock_shared import _require_repo

    repo = _require_repo()
    loop = asyncio.get_running_loop()
    try:
        rows = await loop.run_in_executor(
            None,
            repo.insert_nse_delivery,
            df,
            d,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "Iceberg write failed for nse_delivery on %s",
            d,
        )
        return {
            "date": str(d),
            "status": "failed",
            "rows": 0,
            "error": str(exc),
        }

    return {"date": str(d), "status": "ok", "rows": rows}


async def run_backfill(months: int) -> dict:
    """Backfill the last *months* of NSE bhavcopy data.

    Sequential ingestion with a small sleep between
    days; weekends are skipped (NSE is closed Sat/Sun).
    Holidays surface as ``status="skipped"`` from
    :func:`run_bhavcopy` because the bhavcopy body is
    empty on non-trading days.

    Args:
        months: Number of months to backfill.  Window
            ends at ``today - 1 day`` (T-1).

    Returns:
        Summary dict with ``start_date``, ``end_date``,
        ``ok``, ``skipped``, ``failed``, ``total_rows``,
        ``duration_s``.
    """
    if months <= 0:
        raise ValueError(
            f"months must be > 0, got {months}",
        )

    end_d = date.today() - timedelta(days=1)
    start_d = end_d - timedelta(days=months * 31)

    cur = start_d
    ok = 0
    skipped = 0
    failed = 0
    total_rows = 0
    t_batch = time.monotonic()

    while cur <= end_d:
        if cur.weekday() >= 5:  # Sat/Sun
            cur += timedelta(days=1)
            continue
        result = await run_bhavcopy(cur)
        if result["status"] == "ok":
            ok += 1
            total_rows += result["rows"]
        elif result["status"] == "skipped":
            skipped += 1
        else:
            failed += 1
        await asyncio.sleep(_BACKFILL_INTER_DAY_SLEEP_S)
        cur += timedelta(days=1)

    duration_s = round(time.monotonic() - t_batch, 2)
    _logger.info(
        "Bhavcopy backfill %s..%s done: ok=%d "
        "skipped=%d failed=%d rows=%d in %.1fs",
        start_d,
        end_d,
        ok,
        skipped,
        failed,
        total_rows,
        duration_s,
    )
    return {
        "start_date": str(start_d),
        "end_date": str(end_d),
        "ok": ok,
        "skipped": skipped,
        "failed": failed,
        "total_rows": total_rows,
        "duration_s": duration_s,
    }
