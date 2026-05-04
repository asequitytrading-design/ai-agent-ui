"""Daily fundamentals-snapshot aggregator (Sprint 9).

Builds ``stocks.fundamentals_snapshot`` — a small daily
table of pre-computed multi-year growth ratios + ROCE +
YoY metrics for every ticker that has quarterly history.
The Sprint 9 ``/v1/advanced-analytics/`` endpoints (AA-7)
join this table for the ``sales_3y_cagr``,
``prft_3y_cagr``, ``sales_5y_cagr``, ``prft_5y_cagr``,
``yoy_qtr_prft``, ``yoy_qtr_sales``, ``debt_to_eq``, and
``roce`` columns.

The job is **idempotent** — a fresh run for the same
``snapshot_date`` replaces any prior rows for that date
(scoped pre-delete in
:meth:`StockRepository.insert_fundamentals_snapshot`).

Source table ``stocks.quarterly_results`` is sparse:
each (ticker, quarter_end) emits up to three rows keyed
by ``statement_type``:

- ``income``   — revenue, net_income, operating_income
- ``balance``  — total_debt, total_equity, total_assets,
                 cash_and_equivalents,
                 current_assets, current_liabilities
- ``cashflow`` — operating_cashflow, capex, free_cashflow

We pivot once via DuckDB then compute per-ticker windowed
ratios in pandas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)


# Number of quarters back used for each window.  Indian
# fiscal calendars are quarterly, so 4Q = 1y.
_YOY_QTRS = 4
_3Y_QTRS = 12
_5Y_QTRS = 20


def _cagr(end: float, start: float, years: int) -> float:
    """Compound annual growth rate; NaN-safe.

    Returns NaN when either side is non-positive (negative
    or zero earnings would make the Nth root undefined or
    return imaginary results) or when *start* is too
    small to be meaningful.

    Args:
        end: Most recent period value.
        start: Period value *years* years ago.
        years: Compounding window in years.

    Returns:
        CAGR as a fraction (e.g. ``0.18`` for +18 %), or
        ``float("nan")`` when undefined.
    """
    if not (np.isfinite(end) and np.isfinite(start)):
        return float("nan")
    if start <= 0 or end <= 0 or years <= 0:
        return float("nan")
    return float((end / start) ** (1.0 / years) - 1.0)


def _yoy_change(end: float, start: float) -> float:
    """Year-on-year fractional change; NaN-safe."""
    if not (np.isfinite(end) and np.isfinite(start)):
        return float("nan")
    if start == 0:
        return float("nan")
    return float((end / start) - 1.0)


def _ratio(numerator: float, denominator: float) -> float:
    """Safe division returning NaN on degenerate inputs."""
    if not (np.isfinite(numerator) and np.isfinite(denominator)):
        return float("nan")
    if denominator == 0:
        return float("nan")
    return float(numerator / denominator)


def _per_ticker(
    ticker_df: pd.DataFrame,
) -> dict[str, Any]:
    """Compute the snapshot row for one ticker.

    *ticker_df* is the full quarterly history for the
    ticker, sorted by ``quarter_end`` ascending, with one
    row per ``(quarter_end, statement_type)`` pair.

    Returns a dict matching the
    ``stocks.fundamentals_snapshot`` schema (sans
    ``ticker``, ``snapshot_date``, ``ingested_at`` which
    the caller stamps).
    """
    # Income statement window aggregates ----------------
    income = ticker_df[ticker_df["statement_type"] == "income"].sort_values(
        "quarter_end"
    )
    sales_3y = float("nan")
    sales_5y = float("nan")
    prft_3y = float("nan")
    prft_5y = float("nan")
    yoy_sales = float("nan")
    yoy_prft = float("nan")

    if len(income) > 0:
        rev = income["revenue"].astype(float).values
        ni = income["net_income"].astype(float).values
        end_idx = len(income) - 1
        if end_idx >= _YOY_QTRS:
            yoy_sales = _yoy_change(
                rev[end_idx],
                rev[end_idx - _YOY_QTRS],
            )
            yoy_prft = _yoy_change(
                ni[end_idx],
                ni[end_idx - _YOY_QTRS],
            )
        if end_idx >= _3Y_QTRS:
            sales_3y = _cagr(
                rev[end_idx],
                rev[end_idx - _3Y_QTRS],
                3,
            )
            prft_3y = _cagr(
                ni[end_idx],
                ni[end_idx - _3Y_QTRS],
                3,
            )
        if end_idx >= _5Y_QTRS:
            sales_5y = _cagr(
                rev[end_idx],
                rev[end_idx - _5Y_QTRS],
                5,
            )
            prft_5y = _cagr(
                ni[end_idx],
                ni[end_idx - _5Y_QTRS],
                5,
            )

    # Balance sheet — latest non-NaN row ----------------
    balance = ticker_df[ticker_df["statement_type"] == "balance"].sort_values(
        "quarter_end"
    )
    debt_to_eq = float("nan")
    if not balance.empty:
        latest = balance.iloc[-1]
        debt_to_eq = _ratio(
            float(latest.get("total_debt", float("nan"))),
            float(latest.get("total_equity", float("nan"))),
        )

    # ROCE = operating_income / capital_employed.  Cap-
    # employed proxy = total_equity + total_debt − cash.
    # We need *both* the latest balance row (for capital)
    # and the latest income row (for op_income).
    roce = float("nan")
    if not income.empty and not balance.empty:
        latest_inc = income.iloc[-1]
        latest_bal = balance.iloc[-1]
        op_income = float(
            latest_inc.get(
                "operating_income",
                float("nan"),
            )
        )
        equity = float(latest_bal.get("total_equity", float("nan")))
        debt = float(latest_bal.get("total_debt", float("nan")))
        cash = float(
            latest_bal.get(
                "cash_and_equivalents",
                float("nan"),
            )
        )
        if not np.isnan(cash):
            cap_employed = equity + debt - cash
        else:
            cap_employed = equity + debt
        roce = _ratio(op_income, cap_employed)

    return {
        "sales_3y_cagr": sales_3y,
        "prft_3y_cagr": prft_3y,
        "sales_5y_cagr": sales_5y,
        "prft_5y_cagr": prft_5y,
        "yoy_qtr_prft": yoy_prft,
        "yoy_qtr_sales": yoy_sales,
        "debt_to_eq": debt_to_eq,
        "roce": roce,
    }


def _build_snapshot(
    quarterly: pd.DataFrame,
    snapshot_d: date,
) -> pd.DataFrame:
    """Group *quarterly* by ticker and emit one snapshot row each.

    Args:
        quarterly: Full ``stocks.quarterly_results`` pull
            (filtered to relevant statement types).
        snapshot_d: Snapshot calendar date stamped on every
            output row.

    Returns:
        DataFrame matching the
        ``stocks.fundamentals_snapshot`` schema.
    """
    out: list[dict[str, Any]] = []
    for ticker, sub in quarterly.groupby("ticker"):
        row = _per_ticker(sub)
        row["ticker"] = str(ticker)
        row["snapshot_date"] = snapshot_d
        out.append(row)
    if not out:
        return pd.DataFrame(
            columns=[
                "ticker",
                "snapshot_date",
                "sales_3y_cagr",
                "prft_3y_cagr",
                "sales_5y_cagr",
                "prft_5y_cagr",
                "yoy_qtr_prft",
                "yoy_qtr_sales",
                "debt_to_eq",
                "roce",
            ],
        )
    return pd.DataFrame(out)


async def run_snapshot(
    snapshot_d: date | None = None,
) -> dict:
    """Build today's fundamentals snapshot and persist it.

    Args:
        snapshot_d: Override the snapshot date (mostly
            for tests / backfill).  Defaults to today.

    Returns:
        Summary dict ``{snapshot_date, tickers, rows,
        duration_s}``.
    """
    if snapshot_d is None:
        snapshot_d = date.today()
    t0 = time.monotonic()

    # DuckDB pull of all quarterly history.  This is
    # ~756 tickers × 17 quarters × 3 statements ≈ 38k
    # rows on the dev catalog — single in-memory frame.
    from db.duckdb_engine import query_iceberg_df

    loop = asyncio.get_running_loop()
    sql = (
        "SELECT ticker, quarter_end, statement_type, "
        "revenue, net_income, operating_income, "
        "total_debt, total_equity, total_assets, "
        "cash_and_equivalents "
        "FROM quarterly_results "
        "WHERE statement_type IN ('income', 'balance')"
    )
    quarterly = await loop.run_in_executor(
        None,
        lambda: query_iceberg_df(
            "stocks.quarterly_results",
            sql,
        ),
    )

    if quarterly.empty:
        _logger.warning(
            "No quarterly_results rows — snapshot empty",
        )
        return {
            "snapshot_date": str(snapshot_d),
            "tickers": 0,
            "rows": 0,
            "duration_s": round(
                time.monotonic() - t0,
                2,
            ),
        }

    snap_df = _build_snapshot(quarterly, snapshot_d)
    n_tickers = len(snap_df)

    # Bulk-write through the repo (one Iceberg commit).
    from tools._stock_shared import _require_repo

    repo = _require_repo()
    rows = await loop.run_in_executor(
        None,
        repo.insert_fundamentals_snapshot,
        snap_df,
        snapshot_d,
    )
    duration_s = round(time.monotonic() - t0, 2)
    _logger.info(
        "Fundamentals snapshot for %s: %d tickers, " "%d rows in %.1fs",
        snapshot_d,
        n_tickers,
        rows,
        duration_s,
    )
    return {
        "snapshot_date": str(snapshot_d),
        "tickers": n_tickers,
        "rows": rows,
        "duration_s": duration_s,
    }
