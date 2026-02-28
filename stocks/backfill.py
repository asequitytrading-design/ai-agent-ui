"""One-time backfill of all existing flat-file stock data into Iceberg.

Reads every flat file currently stored under ``data/`` and writes it into
the 8 ``stocks`` Iceberg tables.  The script is **idempotent** — re-running it
will not create duplicate rows because each repository method deduplicates on
its natural key (ticker + date for OHLCV/dividends, etc.).

Backfill order
--------------
1. ``stocks.registry``             — from ``data/metadata/stock_registry.json``
2. ``stocks.company_info``         — from ``data/metadata/{TICKER}_info.json``
3. ``stocks.ohlcv``                — from ``data/raw/{TICKER}_raw.parquet``
4. ``stocks.dividends``            — from ``data/processed/{TICKER}_dividends.parquet``
5. ``stocks.technical_indicators`` — computed from OHLCV via price_analysis_tool
6. ``stocks.analysis_summary``     — computed from OHLCV (skips if today's row exists)
7. ``stocks.forecasts``            — from ``data/forecasts/{TICKER}_{N}m_forecast.parquet``
8. ``stocks.forecast_runs``        — minimal record per forecast file (no accuracy data)

Usage::

    cd ai-agent-ui
    source backend/demoenv/bin/activate
    python stocks/backfill.py

Run this once after ``python stocks/create_tables.py`` to seed historical data.
Subsequent live writes are handled automatically by the backend tool dual-writes.
"""

import datetime as _dt
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Dict

import pandas as pd

# ---------------------------------------------------------------------------
# Bootstrap sys.path so both backend tools and stocks package are importable
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
_BACKEND = _PROJECT_ROOT / "backend"
_BACKEND_TOOLS = _BACKEND / "tools"

for _p in [str(_PROJECT_ROOT), str(_BACKEND), str(_BACKEND_TOOLS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("stocks.backfill")

# ---------------------------------------------------------------------------
# Data paths (mirror backend/tools constants)
# ---------------------------------------------------------------------------

_DATA_RAW = _PROJECT_ROOT / "data" / "raw"
_DATA_PROCESSED = _PROJECT_ROOT / "data" / "processed"
_DATA_FORECASTS = _PROJECT_ROOT / "data" / "forecasts"
_DATA_METADATA = _PROJECT_ROOT / "data" / "metadata"
_REGISTRY_PATH = _DATA_METADATA / "stock_registry.json"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_flat_registry() -> Dict:
    """Load the flat-file stock registry JSON.

    Returns:
        Dict mapping ticker → registry entry, or empty dict if missing.
    """
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        with open(_REGISTRY_PATH, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load stock_registry.json: %s", exc)
        return {}


def _get_market(ticker: str) -> str:
    """Return 'india' for NSE/BSE tickers, 'us' otherwise.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        ``"india"`` or ``"us"``.
    """
    return "india" if ticker.upper().endswith((".NS", ".BO")) else "us"


def _load_currency(ticker: str) -> str:
    """Read ISO currency code from cached metadata JSON.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        ISO 4217 currency code; defaults to ``"USD"``.
    """
    meta_path = _DATA_METADATA / f"{ticker}_info.json"
    try:
        with open(meta_path, "r") as f:
            data = json.load(f)
        return data.get("currency", "USD") or "USD"
    except Exception:
        return "USD"


# ---------------------------------------------------------------------------
# Backfill steps
# ---------------------------------------------------------------------------


def backfill_registry(repo, registry: Dict) -> None:
    """Step 1: Populate stocks.registry from stock_registry.json.

    Args:
        repo: :class:`~stocks.repository.StockRepository` instance.
        registry: Dict loaded from ``stock_registry.json``.
    """
    logger.info("── Step 1: registry (%d tickers)", len(registry))
    ok = fail = 0
    for ticker, entry in registry.items():
        try:
            dr = entry.get("date_range", {})
            repo.upsert_registry(
                ticker=ticker,
                last_fetch_date=date.fromisoformat(entry["last_fetch_date"]),
                total_rows=entry["total_rows"],
                date_range_start=date.fromisoformat(dr["start"]),
                date_range_end=date.fromisoformat(dr["end"]),
                market=_get_market(ticker),
            )
            logger.debug("  registry: %s ✓", ticker)
            ok += 1
        except Exception as exc:
            logger.warning("  registry: %s FAILED — %s", ticker, exc)
            fail += 1
    logger.info("  registry done: %d ok, %d failed", ok, fail)


def backfill_company_info(repo, registry: Dict) -> None:
    """Step 2: Populate stocks.company_info from {TICKER}_info.json files.

    Skips tickers that already have a record in the table.

    Args:
        repo: :class:`~stocks.repository.StockRepository` instance.
        registry: Dict loaded from ``stock_registry.json``.
    """
    logger.info("── Step 2: company_info")
    ok = skip = fail = 0
    for ticker in registry:
        info_path = _DATA_METADATA / f"{ticker}_info.json"
        if not info_path.exists():
            logger.debug("  company_info: %s — no JSON, skip", ticker)
            skip += 1
            continue
        if repo.get_latest_company_info(ticker) is not None:
            logger.debug("  company_info: %s — already exists, skip", ticker)
            skip += 1
            continue
        try:
            with open(info_path, "r") as f:
                raw = json.load(f)
            raw.pop("_fetched_date", None)
            repo.insert_company_info(ticker, raw)
            logger.debug("  company_info: %s ✓", ticker)
            ok += 1
        except Exception as exc:
            logger.warning("  company_info: %s FAILED — %s", ticker, exc)
            fail += 1
    logger.info("  company_info done: %d ok, %d skipped, %d failed", ok, skip, fail)


def backfill_ohlcv(repo, registry: Dict) -> None:
    """Step 3: Populate stocks.ohlcv from {TICKER}_raw.parquet files.

    Args:
        repo: :class:`~stocks.repository.StockRepository` instance.
        registry: Dict loaded from ``stock_registry.json``.
    """
    logger.info("── Step 3: ohlcv")
    total_inserted = 0
    fail = 0
    for ticker in registry:
        parquet_path = _DATA_RAW / f"{ticker}_raw.parquet"
        if not parquet_path.exists():
            logger.debug("  ohlcv: %s — no parquet, skip", ticker)
            continue
        try:
            df = pd.read_parquet(parquet_path, engine="pyarrow")
            df.index = pd.to_datetime(df.index).tz_localize(None)
            inserted = repo.insert_ohlcv(ticker, df)
            total_inserted += inserted
            logger.info("  ohlcv: %s — %d new rows", ticker, inserted)
        except Exception as exc:
            logger.warning("  ohlcv: %s FAILED — %s", ticker, exc)
            fail += 1
    logger.info("  ohlcv done: %d total rows inserted, %d failed", total_inserted, fail)


def backfill_dividends(repo, registry: Dict) -> None:
    """Step 4: Populate stocks.dividends from {TICKER}_dividends.parquet files.

    Args:
        repo: :class:`~stocks.repository.StockRepository` instance.
        registry: Dict loaded from ``stock_registry.json``.
    """
    logger.info("── Step 4: dividends")
    ok = skip = fail = 0
    for ticker in registry:
        div_path = _DATA_PROCESSED / f"{ticker}_dividends.parquet"
        if not div_path.exists():
            skip += 1
            continue
        try:
            df = pd.read_parquet(div_path, engine="pyarrow")
            currency = _load_currency(ticker)
            inserted = repo.insert_dividends(ticker, df, currency=currency)
            logger.info("  dividends: %s — %d rows", ticker, inserted)
            ok += 1
        except Exception as exc:
            logger.warning("  dividends: %s FAILED — %s", ticker, exc)
            fail += 1
    logger.info("  dividends done: %d ok, %d skipped (no file), %d failed", ok, skip, fail)


def backfill_technical_indicators(repo, registry: Dict) -> None:
    """Step 5: Compute and populate stocks.technical_indicators from OHLCV.

    Imports the private helper from :mod:`price_analysis_tool` directly to
    avoid duplicating the indicator logic.

    Args:
        repo: :class:`~stocks.repository.StockRepository` instance.
        registry: Dict loaded from ``stock_registry.json``.
    """
    logger.info("── Step 5: technical_indicators")
    try:
        from price_analysis_tool import _calculate_technical_indicators  # noqa: PLC0415
    except ImportError as exc:
        logger.warning("  Cannot import _calculate_technical_indicators — skip: %s", exc)
        return

    ok = fail = 0
    for ticker in registry:
        parquet_path = _DATA_RAW / f"{ticker}_raw.parquet"
        if not parquet_path.exists():
            continue
        try:
            df = pd.read_parquet(parquet_path, engine="pyarrow")
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df_ind = _calculate_technical_indicators(df)
            repo.upsert_technical_indicators(ticker, df_ind)
            logger.info("  technical_indicators: %s ✓ (%d rows)", ticker, len(df_ind))
            ok += 1
        except Exception as exc:
            logger.warning("  technical_indicators: %s FAILED — %s", ticker, exc)
            fail += 1
    logger.info("  technical_indicators done: %d ok, %d failed", ok, fail)


def backfill_analysis_summary(repo, registry: Dict) -> None:
    """Step 6: Compute and populate stocks.analysis_summary from OHLCV.

    Skips a ticker when today's summary row already exists (idempotent).
    Imports the private helpers from :mod:`price_analysis_tool` directly.

    Args:
        repo: :class:`~stocks.repository.StockRepository` instance.
        registry: Dict loaded from ``stock_registry.json``.
    """
    logger.info("── Step 6: analysis_summary")
    try:
        from price_analysis_tool import (  # noqa: PLC0415
            _calculate_technical_indicators,
            _analyse_price_movement,
            _generate_summary_stats,
        )
    except ImportError as exc:
        logger.warning("  Cannot import analysis helpers — skip: %s", exc)
        return

    today_str = str(date.today())
    ok = skip = fail = 0
    for ticker in registry:
        parquet_path = _DATA_RAW / f"{ticker}_raw.parquet"
        if not parquet_path.exists():
            skip += 1
            continue
        # Skip if today's summary already present
        existing = repo.get_latest_analysis_summary(ticker)
        if existing and str(existing.get("analysis_date", "")) == today_str:
            logger.debug("  analysis_summary: %s — today's row exists, skip", ticker)
            skip += 1
            continue
        try:
            df = pd.read_parquet(parquet_path, engine="pyarrow")
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = _calculate_technical_indicators(df)
            movement = _analyse_price_movement(df)
            stats = _generate_summary_stats(df, ticker)
            combined = {
                **movement,
                **stats,
                "macd_signal_text": stats.get("macd_signal"),
                "support_levels": str(movement.get("support_levels", [])),
                "resistance_levels": str(movement.get("resistance_levels", [])),
            }
            repo.insert_analysis_summary(ticker, combined)
            logger.info("  analysis_summary: %s ✓", ticker)
            ok += 1
        except Exception as exc:
            logger.warning("  analysis_summary: %s FAILED — %s", ticker, exc)
            fail += 1
    logger.info("  analysis_summary done: %d ok, %d skipped, %d failed", ok, skip, fail)


def backfill_forecasts(repo, registry: Dict) -> None:
    """Steps 7–8: Populate stocks.forecasts and stocks.forecast_runs.

    Reads every ``{TICKER}_{N}m_forecast.parquet`` and inserts the forecast
    series.  A minimal run metadata row is created (no accuracy/sentiment since
    these are not stored in the parquet files).  The file modification time is
    used as the approximate ``run_date``.

    Args:
        repo: :class:`~stocks.repository.StockRepository` instance.
        registry: Dict loaded from ``stock_registry.json``.
    """
    logger.info("── Steps 7–8: forecasts + forecast_runs")
    ok = skip = fail = 0
    for ticker in registry:
        for months in [3, 6, 9]:
            parquet_path = _DATA_FORECASTS / f"{ticker}_{months}m_forecast.parquet"
            if not parquet_path.exists():
                continue
            try:
                forecast_df = pd.read_parquet(parquet_path, engine="pyarrow")
                if forecast_df.empty:
                    skip += 1
                    continue

                # Use file mtime as approximate run_date
                mtime = parquet_path.stat().st_mtime
                run_date = _dt.datetime.fromtimestamp(mtime).date()

                # Skip if this run_date series already stored
                existing_run = repo.get_latest_forecast_run(ticker, months)
                if existing_run and str(existing_run.get("run_date", "")) == str(run_date):
                    logger.debug(
                        "  forecasts: %s %dm run %s — already stored, skip",
                        ticker, months, run_date,
                    )
                    skip += 1
                    continue

                repo.insert_forecast_series(ticker, months, run_date, forecast_df)
                # Minimal run row (no accuracy/sentiment available from parquet)
                repo.insert_forecast_run(ticker, months, {"run_date": run_date})
                logger.info(
                    "  forecasts: %s %dm ✓ (%d rows, run_date=%s)",
                    ticker, months, len(forecast_df), run_date,
                )
                ok += 1
            except Exception as exc:
                logger.warning("  forecasts: %s %dm FAILED — %s", ticker, months, exc)
                fail += 1
    logger.info("  forecasts done: %d ok, %d skipped, %d failed", ok, skip, fail)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the full backfill pipeline.

    Ensures tables exist via :func:`~stocks.create_tables.create_tables`,
    then runs all 8 backfill steps in dependency order.
    """
    logger.info("=== Iceberg stock data backfill ===")

    # Ensure Iceberg tables are initialised
    logger.info("Ensuring Iceberg tables exist...")
    from stocks.create_tables import create_tables  # noqa: PLC0415
    create_tables()

    from stocks.repository import StockRepository  # noqa: PLC0415
    repo = StockRepository()

    registry = _load_flat_registry()
    if not registry:
        logger.warning("stock_registry.json is empty or missing — nothing to backfill.")
        return

    logger.info("Found %d tickers: %s", len(registry), sorted(registry.keys()))

    backfill_registry(repo, registry)
    backfill_company_info(repo, registry)
    backfill_ohlcv(repo, registry)
    backfill_dividends(repo, registry)
    backfill_technical_indicators(repo, registry)
    backfill_analysis_summary(repo, registry)
    backfill_forecasts(repo, registry)

    logger.info("=== Backfill complete ===")


if __name__ == "__main__":
    main()
