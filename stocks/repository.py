"""Iceberg-backed repository for all stock market data tables.

This module provides :class:`StockRepository`, the single point of access
for reading and writing to the 8 ``stocks`` Iceberg tables.  No code
outside this module should interact with the tables directly.

Write semantics
---------------
- **registry** — upsert (copy-on-write): read full table, update or append
  the row for ``ticker``, overwrite.
- **company_info** — append-only snapshots; never updated or deleted.
- **ohlcv** — append new rows; deduplication on ``(ticker, date)`` at
  application level (existing rows are never re-inserted).
- **dividends** — same as ohlcv: append, deduplicate on ``(ticker, ex_date)``.
- **technical_indicators** — upsert per ``(ticker, date)`` (copy-on-write for
  the ticker partition; acceptable for typical dataset sizes < 5 000 rows/ticker).
- **analysis_summary** — append-only snapshots.
- **forecast_runs** — append-only per ``(ticker, horizon_months, run_date)``.
- **forecasts** — append per ``(ticker, horizon_months, run_date)``; existing
  series for the same run are dropped before re-inserting.

PyIceberg quirks
----------------
- ``table.append()`` requires a ``pa.Table`` (not a ``RecordBatch``).
- ``TimestampType`` maps to ``pa.timestamp("us")`` — pass naive UTC datetimes.
- Overwrite uses ``table.overwrite(df)`` which replaces *all* data; for
  partitioned tables use ``table.dynamic_partition_overwrite(df)`` to replace
  only the affected partition.

Usage::

    from stocks.repository import StockRepository
    from datetime import date

    repo = StockRepository()
    repo.upsert_registry("AAPL", date.today(), 2500, date(2015,1,2), date(2026,2,28), "us")
    df = repo.get_ohlcv("AAPL")
"""

import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow as pa

_logger = logging.getLogger(__name__)

_NAMESPACE = "stocks"
_REGISTRY = f"{_NAMESPACE}.registry"
_COMPANY_INFO = f"{_NAMESPACE}.company_info"
_OHLCV = f"{_NAMESPACE}.ohlcv"
_DIVIDENDS = f"{_NAMESPACE}.dividends"
_TECHNICAL_INDICATORS = f"{_NAMESPACE}.technical_indicators"
_ANALYSIS_SUMMARY = f"{_NAMESPACE}.analysis_summary"
_FORECAST_RUNS = f"{_NAMESPACE}.forecast_runs"
_FORECASTS = f"{_NAMESPACE}.forecasts"


def _now_utc() -> datetime:
    """Return current UTC time as a naive datetime (PyIceberg TimestampType compat).

    Returns:
        Naive :class:`datetime.datetime` in UTC.
    """
    return datetime.utcnow()


def _to_date(value: Any) -> Optional[date]:
    """Coerce a value to a :class:`datetime.date`, or return ``None``.

    Args:
        value: A ``date``, ``datetime``, ISO string, or ``None``.

    Returns:
        A :class:`datetime.date` or ``None`` if conversion fails.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def _safe_float(value: Any) -> Optional[float]:
    """Convert *value* to float, returning ``None`` on failure or NaN.

    Args:
        value: Any numeric-like value.

    Returns:
        Float or ``None``.
    """
    try:
        f = float(value)
        import math
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Convert *value* to int, returning ``None`` on failure.

    Args:
        value: Any numeric-like value.

    Returns:
        int or ``None``.
    """
    try:
        return int(value)
    except Exception:
        return None


class StockRepository:
    """Repository for all 8 ``stocks`` Iceberg tables.

    Instantiate once and reuse; the catalog is loaded lazily on first access.

    Example:
        >>> repo = StockRepository()  # doctest: +SKIP
        >>> repo.upsert_registry("AAPL", ...)  # doctest: +SKIP
    """

    def __init__(self) -> None:
        """Initialise the repository without loading the catalog yet."""
        self._catalog = None

    # ------------------------------------------------------------------
    # Catalog access
    # ------------------------------------------------------------------

    def _get_catalog(self):
        """Return (and cache) the Iceberg SqlCatalog.

        Returns:
            The loaded :class:`pyiceberg.catalog.sql.SqlCatalog` instance.
        """
        if self._catalog is None:
            from pyiceberg.catalog import load_catalog
            self._catalog = load_catalog("local")
        return self._catalog

    def _load_table(self, identifier: str):
        """Load an Iceberg table by its fully-qualified identifier.

        Args:
            identifier: e.g. ``"stocks.ohlcv"``.

        Returns:
            The loaded Iceberg table object.
        """
        return self._get_catalog().load_table(identifier)

    def _table_to_df(self, identifier: str) -> pd.DataFrame:
        """Read an entire Iceberg table into a pandas DataFrame.

        Args:
            identifier: Fully-qualified table name.

        Returns:
            pandas DataFrame with all rows, or an empty DataFrame on error.
        """
        try:
            tbl = self._load_table(identifier)
            return tbl.scan().to_pandas()
        except Exception as exc:
            _logger.warning("Could not read table %s: %s", identifier, exc)
            return pd.DataFrame()

    def _append_rows(self, identifier: str, arrow_table: pa.Table) -> None:
        """Append a PyArrow table to an Iceberg table.

        Args:
            identifier: Fully-qualified table name.
            arrow_table: Rows to append (must match the table schema).
        """
        tbl = self._load_table(identifier)
        tbl.append(arrow_table)

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def upsert_registry(
        self,
        ticker: str,
        last_fetch_date: date,
        total_rows: int,
        date_range_start: date,
        date_range_end: date,
        market: str,
    ) -> None:
        """Insert or update the registry row for *ticker*.

        Uses copy-on-write: reads full table, updates or appends the row,
        then overwrites.

        Args:
            ticker: Stock ticker symbol (already uppercased).
            last_fetch_date: Date of the most recent successful Yahoo Finance pull.
            total_rows: Total OHLCV row count for this ticker.
            date_range_start: Earliest trading date in OHLCV.
            date_range_end: Most recent trading date in OHLCV.
            market: ``"india"`` for .NS/.BO tickers, ``"us"`` otherwise.
        """
        now = _now_utc()
        df = self._table_to_df(_REGISTRY)

        new_row = {
            "ticker": ticker,
            "last_fetch_date": last_fetch_date,
            "total_rows": int(total_rows),
            "date_range_start": date_range_start,
            "date_range_end": date_range_end,
            "market": market,
            "created_at": now,
            "updated_at": now,
        }

        if not df.empty and ticker in df["ticker"].values:
            created_at = df.loc[df["ticker"] == ticker, "created_at"].iloc[0]
            new_row["created_at"] = created_at
            df = df[df["ticker"] != ticker]

        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

        arrow_tbl = pa.Table.from_pandas(df, schema=pa.schema([
            pa.field("ticker", pa.string()),
            pa.field("last_fetch_date", pa.date32()),
            pa.field("total_rows", pa.int64()),
            pa.field("date_range_start", pa.date32()),
            pa.field("date_range_end", pa.date32()),
            pa.field("market", pa.string()),
            pa.field("created_at", pa.timestamp("us")),
            pa.field("updated_at", pa.timestamp("us")),
        ]), preserve_index=False)

        tbl = self._load_table(_REGISTRY)
        tbl.overwrite(arrow_tbl)
        _logger.debug("Registry upserted for %s", ticker)

    def get_registry(self, ticker: Optional[str] = None) -> pd.DataFrame:
        """Return registry rows, optionally filtered to a single ticker.

        Args:
            ticker: If provided, return only the row for this ticker.
                    If ``None``, return all rows.

        Returns:
            pandas DataFrame with registry rows.
        """
        df = self._table_to_df(_REGISTRY)
        if ticker and not df.empty:
            df = df[df["ticker"] == ticker.upper()]
        return df

    # ------------------------------------------------------------------
    # Company info
    # ------------------------------------------------------------------

    def insert_company_info(self, ticker: str, info: Dict[str, Any]) -> None:
        """Append a company metadata snapshot for *ticker*.

        Args:
            ticker: Stock ticker symbol (already uppercased).
            info: Dict from ``yf.Ticker(ticker).info`` plus optional extra fields.
        """
        row = pa.table({
            "info_id": pa.array([str(uuid.uuid4())], pa.string()),
            "ticker": pa.array([ticker], pa.string()),
            "company_name": pa.array([str(info.get("company_name") or info.get("longName") or "")], pa.string()),
            "sector": pa.array([info.get("sector")], pa.string()),
            "industry": pa.array([info.get("industry")], pa.string()),
            "market_cap": pa.array([_safe_int(info.get("market_cap") or info.get("marketCap"))], pa.int64()),
            "pe_ratio": pa.array([_safe_float(info.get("pe_ratio") or info.get("trailingPE"))], pa.float64()),
            "week_52_high": pa.array([_safe_float(info.get("52w_high") or info.get("fiftyTwoWeekHigh"))], pa.float64()),
            "week_52_low": pa.array([_safe_float(info.get("52w_low") or info.get("fiftyTwoWeekLow"))], pa.float64()),
            "current_price": pa.array([_safe_float(info.get("current_price") or info.get("currentPrice"))], pa.float64()),
            "currency": pa.array([str(info.get("currency") or "USD")], pa.string()),
            "fetched_at": pa.array([_now_utc()], pa.timestamp("us")),
            "exchange": pa.array([info.get("exchange")], pa.string()),
            "country": pa.array([info.get("country")], pa.string()),
            "employees": pa.array([_safe_int(info.get("fullTimeEmployees"))], pa.int64()),
            "dividend_yield": pa.array([_safe_float(info.get("dividendYield"))], pa.float64()),
            "beta": pa.array([_safe_float(info.get("beta"))], pa.float64()),
            "book_value": pa.array([_safe_float(info.get("bookValue"))], pa.float64()),
            "price_to_book": pa.array([_safe_float(info.get("priceToBook"))], pa.float64()),
            "earnings_growth": pa.array([_safe_float(info.get("earningsGrowth"))], pa.float64()),
            "revenue_growth": pa.array([_safe_float(info.get("revenueGrowth"))], pa.float64()),
            "profit_margins": pa.array([_safe_float(info.get("profitMargins"))], pa.float64()),
            "avg_volume": pa.array([_safe_int(info.get("averageVolume"))], pa.int64()),
            "float_shares": pa.array([_safe_int(info.get("floatShares"))], pa.int64()),
            "short_ratio": pa.array([_safe_float(info.get("shortRatio"))], pa.float64()),
            "analyst_target": pa.array([_safe_float(info.get("targetMeanPrice"))], pa.float64()),
            "recommendation": pa.array([_safe_float(info.get("recommendationMean"))], pa.float64()),
        })
        self._append_rows(_COMPANY_INFO, row)
        _logger.debug("company_info snapshot appended for %s", ticker)

    def get_latest_company_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Return the most recent company metadata snapshot for *ticker*.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict of company info fields, or ``None`` if no record exists.
        """
        df = self._table_to_df(_COMPANY_INFO)
        if df.empty:
            return None
        df = df[df["ticker"] == ticker.upper()]
        if df.empty:
            return None
        latest = df.sort_values("fetched_at", ascending=False).iloc[0]
        return latest.to_dict()

    def get_all_latest_company_info(self) -> pd.DataFrame:
        """Return the most recent snapshot for every ticker.

        Returns:
            DataFrame with one row per ticker (latest ``fetched_at``).
        """
        df = self._table_to_df(_COMPANY_INFO)
        if df.empty:
            return df
        return (
            df.sort_values("fetched_at", ascending=False)
            .groupby("ticker", as_index=False)
            .first()
        )

    # ------------------------------------------------------------------
    # OHLCV
    # ------------------------------------------------------------------

    def insert_ohlcv(self, ticker: str, df: pd.DataFrame) -> int:
        """Append new OHLCV rows for *ticker*, skipping existing (ticker, date) pairs.

        Args:
            ticker: Stock ticker symbol (already uppercased).
            df: DataFrame with DatetimeIndex and columns Open, High, Low, Close,
                Adj Close (optional), Volume as returned by yfinance.

        Returns:
            Number of new rows actually inserted.
        """
        if df.empty:
            return 0

        # Normalise index to date
        dates = pd.to_datetime(df.index).date

        # Find already-stored dates to skip duplicates
        existing_df = self._table_to_df(_OHLCV)
        if not existing_df.empty:
            existing_dates = set(
                existing_df[existing_df["ticker"] == ticker]["date"].astype(str)
            )
        else:
            existing_dates = set()

        rows = []
        now = _now_utc()
        for i, (dt, row) in enumerate(zip(dates, df.itertuples())):
            if str(dt) in existing_dates:
                continue
            rows.append({
                "ticker": ticker,
                "date": dt,
                "open": _safe_float(row.Open),
                "high": _safe_float(row.High),
                "low": _safe_float(row.Low),
                "close": _safe_float(row.Close),
                "adj_close": _safe_float(getattr(row, "Adj_Close", None) or getattr(row, "Adj Close", None)),
                "volume": _safe_int(row.Volume),
                "fetched_at": now,
            })

        if not rows:
            _logger.debug("No new OHLCV rows to insert for %s", ticker)
            return 0

        new_df = pd.DataFrame(rows)
        arrow_tbl = pa.table({
            "ticker": pa.array(new_df["ticker"].tolist(), pa.string()),
            "date": pa.array(new_df["date"].tolist(), pa.date32()),
            "open": pa.array(new_df["open"].tolist(), pa.float64()),
            "high": pa.array(new_df["high"].tolist(), pa.float64()),
            "low": pa.array(new_df["low"].tolist(), pa.float64()),
            "close": pa.array(new_df["close"].tolist(), pa.float64()),
            "adj_close": pa.array(new_df["adj_close"].tolist(), pa.float64()),
            "volume": pa.array(new_df["volume"].tolist(), pa.int64()),
            "fetched_at": pa.array(new_df["fetched_at"].tolist(), pa.timestamp("us")),
        })
        self._append_rows(_OHLCV, arrow_tbl)
        _logger.debug("Inserted %d new OHLCV rows for %s", len(rows), ticker)
        return len(rows)

    def get_ohlcv(
        self,
        ticker: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> pd.DataFrame:
        """Return OHLCV data for *ticker*, optionally filtered by date range.

        Args:
            ticker: Stock ticker symbol.
            start: Inclusive start date (``None`` = no lower bound).
            end: Inclusive end date (``None`` = no upper bound).

        Returns:
            DataFrame sorted by date ascending with columns:
            ticker, date, open, high, low, close, adj_close, volume.
        """
        df = self._table_to_df(_OHLCV)
        if df.empty:
            return df
        df = df[df["ticker"] == ticker.upper()].copy()
        if start:
            df = df[pd.to_datetime(df["date"]).dt.date >= start]
        if end:
            df = df[pd.to_datetime(df["date"]).dt.date <= end]
        return df.sort_values("date").reset_index(drop=True)

    def get_latest_ohlcv_date(self, ticker: str) -> Optional[date]:
        """Return the most recent OHLCV date stored for *ticker*.

        Used by the delta fetch logic to determine how much new data to fetch.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            :class:`datetime.date` or ``None`` if no data exists.
        """
        df = self._table_to_df(_OHLCV)
        if df.empty:
            return None
        df = df[df["ticker"] == ticker.upper()]
        if df.empty:
            return None
        latest = pd.to_datetime(df["date"]).max()
        return latest.date() if pd.notna(latest) else None

    # ------------------------------------------------------------------
    # Dividends
    # ------------------------------------------------------------------

    def insert_dividends(
        self, ticker: str, df: pd.DataFrame, currency: str = "USD"
    ) -> int:
        """Append dividend rows for *ticker*, skipping existing (ticker, ex_date) pairs.

        Args:
            ticker: Stock ticker symbol.
            df: DataFrame with columns ``date`` and ``dividend`` (from yfinance).
            currency: ISO currency code for this ticker, e.g. ``"INR"``.
                Defaults to ``"USD"``.

        Returns:
            Number of new rows inserted.
        """
        if df.empty:
            return 0

        existing_df = self._table_to_df(_DIVIDENDS)
        if not existing_df.empty:
            existing_dates = set(
                existing_df[existing_df["ticker"] == ticker]["ex_date"].astype(str)
            )
        else:
            existing_dates = set()
        now = _now_utc()
        rows = []
        for _, row in df.iterrows():
            ex_dt = _to_date(row.get("date", row.name))
            if ex_dt is None or str(ex_dt) in existing_dates:
                continue
            rows.append({
                "ticker": ticker,
                "ex_date": ex_dt,
                "dividend_amount": _safe_float(row.get("dividend", row.iloc[0])),
                "currency": currency,
                "fetched_at": now,
            })

        if not rows:
            return 0

        new_df = pd.DataFrame(rows)
        arrow_tbl = pa.table({
            "ticker": pa.array(new_df["ticker"].tolist(), pa.string()),
            "ex_date": pa.array(new_df["ex_date"].tolist(), pa.date32()),
            "dividend_amount": pa.array(new_df["dividend_amount"].tolist(), pa.float64()),
            "currency": pa.array(new_df["currency"].tolist(), pa.string()),
            "fetched_at": pa.array(new_df["fetched_at"].tolist(), pa.timestamp("us")),
        })
        self._append_rows(_DIVIDENDS, arrow_tbl)
        _logger.debug("Inserted %d new dividend rows for %s", len(rows), ticker)
        return len(rows)

    def get_dividends(self, ticker: str) -> pd.DataFrame:
        """Return dividend history for *ticker* sorted by ex_date ascending.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            DataFrame with columns: ticker, ex_date, dividend_amount, currency.
        """
        df = self._table_to_df(_DIVIDENDS)
        if df.empty:
            return df
        return (
            df[df["ticker"] == ticker.upper()]
            .sort_values("ex_date")
            .reset_index(drop=True)
        )

    # ------------------------------------------------------------------
    # Technical indicators
    # ------------------------------------------------------------------

    def upsert_technical_indicators(self, ticker: str, df: pd.DataFrame) -> None:
        """Insert or update technical indicator rows for *ticker*.

        Replaces all existing rows for this ticker (partition overwrite).

        Args:
            ticker: Stock ticker symbol.
            df: DataFrame with DatetimeIndex and indicator columns:
                sma_50, sma_200, ema_20, rsi_14, macd, macd_signal, macd_hist,
                bb_upper, bb_middle, bb_lower, atr_14. May also contain
                a ``daily_return`` column.
        """
        if df.empty:
            return

        now = _now_utc()
        dates = pd.to_datetime(df.index).date

        rows = {
            "ticker": [],
            "date": [],
            "sma_50": [],
            "sma_200": [],
            "ema_20": [],
            "rsi_14": [],
            "macd": [],
            "macd_signal": [],
            "macd_hist": [],
            "bb_upper": [],
            "bb_middle": [],
            "bb_lower": [],
            "atr_14": [],
            "daily_return": [],
            "computed_at": [],
        }

        def _col(name: str) -> Optional[float]:
            """Extract column value by name, tolerating missing columns."""
            if name in df.columns:
                return _safe_float(row_vals.get(name))
            return None

        for dt, (_, row_series) in zip(dates, df.iterrows()):
            row_vals = row_series.to_dict()
            rows["ticker"].append(ticker)
            rows["date"].append(dt)
            rows["sma_50"].append(_safe_float(row_vals.get("SMA_50") or row_vals.get("sma_50")))
            rows["sma_200"].append(_safe_float(row_vals.get("SMA_200") or row_vals.get("sma_200")))
            rows["ema_20"].append(_safe_float(row_vals.get("EMA_20") or row_vals.get("ema_20")))
            rows["rsi_14"].append(_safe_float(row_vals.get("RSI_14") or row_vals.get("rsi_14")))
            rows["macd"].append(_safe_float(row_vals.get("MACD") or row_vals.get("macd")))
            rows["macd_signal"].append(_safe_float(row_vals.get("MACD_Signal") or row_vals.get("macd_signal")))
            rows["macd_hist"].append(_safe_float(row_vals.get("MACD_Hist") or row_vals.get("macd_hist")))
            rows["bb_upper"].append(_safe_float(row_vals.get("BB_Upper") or row_vals.get("bb_upper")))
            rows["bb_middle"].append(_safe_float(row_vals.get("BB_Middle") or row_vals.get("bb_middle")))
            rows["bb_lower"].append(_safe_float(row_vals.get("BB_Lower") or row_vals.get("bb_lower")))
            rows["atr_14"].append(_safe_float(row_vals.get("ATR_14") or row_vals.get("atr_14")))
            rows["daily_return"].append(_safe_float(row_vals.get("daily_return")))
            rows["computed_at"].append(now)

        arrow_tbl = pa.table({
            "ticker": pa.array(rows["ticker"], pa.string()),
            "date": pa.array(rows["date"], pa.date32()),
            "sma_50": pa.array(rows["sma_50"], pa.float64()),
            "sma_200": pa.array(rows["sma_200"], pa.float64()),
            "ema_20": pa.array(rows["ema_20"], pa.float64()),
            "rsi_14": pa.array(rows["rsi_14"], pa.float64()),
            "macd": pa.array(rows["macd"], pa.float64()),
            "macd_signal": pa.array(rows["macd_signal"], pa.float64()),
            "macd_hist": pa.array(rows["macd_hist"], pa.float64()),
            "bb_upper": pa.array(rows["bb_upper"], pa.float64()),
            "bb_middle": pa.array(rows["bb_middle"], pa.float64()),
            "bb_lower": pa.array(rows["bb_lower"], pa.float64()),
            "atr_14": pa.array(rows["atr_14"], pa.float64()),
            "daily_return": pa.array(rows["daily_return"], pa.float64()),
            "computed_at": pa.array(rows["computed_at"], pa.timestamp("us")),
        })

        # Remove existing rows for this ticker then append fresh data
        existing = self._table_to_df(_TECHNICAL_INDICATORS)
        if not existing.empty:
            existing = existing[existing["ticker"] != ticker]
            # Rebuild full table without this ticker, then append new rows
            rebuilt = pa.Table.from_pandas(existing, schema=arrow_tbl.schema,
                                           preserve_index=False)
            combined = pa.concat_tables([rebuilt, arrow_tbl])
            tbl = self._load_table(_TECHNICAL_INDICATORS)
            tbl.overwrite(combined)
        else:
            self._append_rows(_TECHNICAL_INDICATORS, arrow_tbl)

        _logger.debug("Technical indicators upserted for %s (%d rows)", ticker, len(rows["ticker"]))

    def get_technical_indicators(
        self,
        ticker: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> pd.DataFrame:
        """Return technical indicator rows for *ticker*.

        Args:
            ticker: Stock ticker symbol.
            start: Inclusive start date.
            end: Inclusive end date.

        Returns:
            DataFrame sorted by date ascending.
        """
        df = self._table_to_df(_TECHNICAL_INDICATORS)
        if df.empty:
            return df
        df = df[df["ticker"] == ticker.upper()].copy()
        if start:
            df = df[pd.to_datetime(df["date"]).dt.date >= start]
        if end:
            df = df[pd.to_datetime(df["date"]).dt.date <= end]
        return df.sort_values("date").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Analysis summary
    # ------------------------------------------------------------------

    def insert_analysis_summary(self, ticker: str, summary: Dict[str, Any]) -> None:
        """Append a daily analysis summary snapshot for *ticker*.

        Args:
            ticker: Stock ticker symbol.
            summary: Dict with keys matching the ``stocks.analysis_summary`` schema.
                     ``analysis_date`` defaults to today if not provided.
        """
        today = summary.get("analysis_date") or date.today()
        row = pa.table({
            "summary_id": pa.array([str(uuid.uuid4())], pa.string()),
            "ticker": pa.array([ticker], pa.string()),
            "analysis_date": pa.array([_to_date(today)], pa.date32()),
            "bull_phase_pct": pa.array([_safe_float(summary.get("bull_phase_pct"))], pa.float64()),
            "bear_phase_pct": pa.array([_safe_float(summary.get("bear_phase_pct"))], pa.float64()),
            "max_drawdown_pct": pa.array([_safe_float(summary.get("max_drawdown_pct"))], pa.float64()),
            "max_drawdown_duration_days": pa.array([_safe_int(summary.get("max_drawdown_duration_days"))], pa.int64()),
            "annualized_volatility_pct": pa.array([_safe_float(summary.get("annualized_volatility_pct"))], pa.float64()),
            "annualized_return_pct": pa.array([_safe_float(summary.get("annualized_return_pct"))], pa.float64()),
            "sharpe_ratio": pa.array([_safe_float(summary.get("sharpe_ratio"))], pa.float64()),
            "all_time_high": pa.array([_safe_float(summary.get("all_time_high"))], pa.float64()),
            "all_time_high_date": pa.array([_to_date(summary.get("all_time_high_date"))], pa.date32()),
            "all_time_low": pa.array([_safe_float(summary.get("all_time_low"))], pa.float64()),
            "all_time_low_date": pa.array([_to_date(summary.get("all_time_low_date"))], pa.date32()),
            "support_levels": pa.array([summary.get("support_levels")], pa.string()),
            "resistance_levels": pa.array([summary.get("resistance_levels")], pa.string()),
            "sma_50_signal": pa.array([summary.get("sma_50_signal")], pa.string()),
            "sma_200_signal": pa.array([summary.get("sma_200_signal")], pa.string()),
            "rsi_signal": pa.array([summary.get("rsi_signal")], pa.string()),
            "macd_signal_text": pa.array([summary.get("macd_signal_text")], pa.string()),
            "best_month": pa.array([summary.get("best_month")], pa.string()),
            "worst_month": pa.array([summary.get("worst_month")], pa.string()),
            "best_year": pa.array([summary.get("best_year")], pa.string()),
            "worst_year": pa.array([summary.get("worst_year")], pa.string()),
            "computed_at": pa.array([_now_utc()], pa.timestamp("us")),
        })
        self._append_rows(_ANALYSIS_SUMMARY, row)
        _logger.debug("analysis_summary appended for %s", ticker)

    def get_latest_analysis_summary(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Return the most recent analysis summary for *ticker*.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict of analysis fields, or ``None`` if no record exists.
        """
        df = self._table_to_df(_ANALYSIS_SUMMARY)
        if df.empty:
            return None
        df = df[df["ticker"] == ticker.upper()]
        if df.empty:
            return None
        return df.sort_values("analysis_date", ascending=False).iloc[0].to_dict()

    def get_all_latest_analysis_summary(self) -> pd.DataFrame:
        """Return the most recent analysis summary snapshot for every ticker.

        Returns:
            DataFrame with one row per ticker (latest ``analysis_date``),
            or an empty DataFrame when the table has no rows.
        """
        df = self._table_to_df(_ANALYSIS_SUMMARY)
        if df.empty:
            return df
        return (
            df.sort_values("analysis_date", ascending=False)
            .groupby("ticker", as_index=False)
            .first()
        )

    def get_analysis_history(self, ticker: str) -> pd.DataFrame:
        """Return all analysis summary rows for *ticker* sorted by date ascending.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            DataFrame sorted by analysis_date.
        """
        df = self._table_to_df(_ANALYSIS_SUMMARY)
        if df.empty:
            return df
        return (
            df[df["ticker"] == ticker.upper()]
            .sort_values("analysis_date")
            .reset_index(drop=True)
        )

    # ------------------------------------------------------------------
    # Forecast runs
    # ------------------------------------------------------------------

    def insert_forecast_run(
        self,
        ticker: str,
        horizon_months: int,
        run_dict: Dict[str, Any],
    ) -> None:
        """Append a forecast run metadata row.

        Args:
            ticker: Stock ticker symbol.
            horizon_months: Prophet forecast horizon (3, 6, or 9).
            run_dict: Dict with keys matching ``stocks.forecast_runs`` schema.
        """
        today = run_dict.get("run_date") or date.today()
        row = pa.table({
            "run_id": pa.array([str(uuid.uuid4())], pa.string()),
            "ticker": pa.array([ticker], pa.string()),
            "horizon_months": pa.array([int(horizon_months)], pa.int32()),
            "run_date": pa.array([_to_date(today)], pa.date32()),
            "sentiment": pa.array([run_dict.get("sentiment")], pa.string()),
            "current_price_at_run": pa.array([_safe_float(run_dict.get("current_price_at_run"))], pa.float64()),
            "target_3m_date": pa.array([_to_date(run_dict.get("target_3m_date"))], pa.date32()),
            "target_3m_price": pa.array([_safe_float(run_dict.get("target_3m_price"))], pa.float64()),
            "target_3m_pct_change": pa.array([_safe_float(run_dict.get("target_3m_pct_change"))], pa.float64()),
            "target_3m_lower": pa.array([_safe_float(run_dict.get("target_3m_lower"))], pa.float64()),
            "target_3m_upper": pa.array([_safe_float(run_dict.get("target_3m_upper"))], pa.float64()),
            "target_6m_date": pa.array([_to_date(run_dict.get("target_6m_date"))], pa.date32()),
            "target_6m_price": pa.array([_safe_float(run_dict.get("target_6m_price"))], pa.float64()),
            "target_6m_pct_change": pa.array([_safe_float(run_dict.get("target_6m_pct_change"))], pa.float64()),
            "target_6m_lower": pa.array([_safe_float(run_dict.get("target_6m_lower"))], pa.float64()),
            "target_6m_upper": pa.array([_safe_float(run_dict.get("target_6m_upper"))], pa.float64()),
            "target_9m_date": pa.array([_to_date(run_dict.get("target_9m_date"))], pa.date32()),
            "target_9m_price": pa.array([_safe_float(run_dict.get("target_9m_price"))], pa.float64()),
            "target_9m_pct_change": pa.array([_safe_float(run_dict.get("target_9m_pct_change"))], pa.float64()),
            "target_9m_lower": pa.array([_safe_float(run_dict.get("target_9m_lower"))], pa.float64()),
            "target_9m_upper": pa.array([_safe_float(run_dict.get("target_9m_upper"))], pa.float64()),
            "mae": pa.array([_safe_float(run_dict.get("mae"))], pa.float64()),
            "rmse": pa.array([_safe_float(run_dict.get("rmse"))], pa.float64()),
            "mape": pa.array([_safe_float(run_dict.get("mape"))], pa.float64()),
            "computed_at": pa.array([_now_utc()], pa.timestamp("us")),
        })
        self._append_rows(_FORECAST_RUNS, row)
        _logger.debug("forecast_run appended for %s %dm", ticker, horizon_months)

    def get_latest_forecast_run(
        self, ticker: str, horizon_months: int
    ) -> Optional[Dict[str, Any]]:
        """Return the most recent forecast run for *ticker* and *horizon_months*.

        Args:
            ticker: Stock ticker symbol.
            horizon_months: Forecast horizon (3, 6, or 9).

        Returns:
            Dict of forecast run fields, or ``None`` if no record exists.
        """
        df = self._table_to_df(_FORECAST_RUNS)
        if df.empty:
            return None
        df = df[
            (df["ticker"] == ticker.upper()) &
            (df["horizon_months"] == int(horizon_months))
        ]
        if df.empty:
            return None
        return df.sort_values("run_date", ascending=False).iloc[0].to_dict()

    # ------------------------------------------------------------------
    # Forecast series
    # ------------------------------------------------------------------

    def insert_forecast_series(
        self,
        ticker: str,
        horizon_months: int,
        run_date: date,
        forecast_df: pd.DataFrame,
    ) -> None:
        """Append the full Prophet output series for a forecast run.

        Drops any existing rows for the same ``(ticker, horizon_months, run_date)``
        before inserting to keep the table clean on re-runs.

        Args:
            ticker: Stock ticker symbol.
            horizon_months: Forecast horizon (3, 6, or 9).
            run_date: The date this forecast was run.
            forecast_df: DataFrame with columns ``ds``, ``yhat``, ``yhat_lower``,
                ``yhat_upper`` as returned by Prophet.
        """
        if forecast_df.empty:
            return

        run_date = _to_date(run_date)

        # Remove existing rows for this exact run
        existing = self._table_to_df(_FORECASTS)
        if not existing.empty:
            mask = (
                (existing["ticker"] == ticker) &
                (existing["horizon_months"] == int(horizon_months)) &
                (existing["run_date"].astype(str) == str(run_date))
            )
            existing = existing[~mask]

        new_rows = {
            "ticker": [ticker] * len(forecast_df),
            "horizon_months": [int(horizon_months)] * len(forecast_df),
            "run_date": [run_date] * len(forecast_df),
            "forecast_date": [_to_date(d) for d in forecast_df["ds"]],
            "predicted_price": [_safe_float(v) for v in forecast_df["yhat"]],
            "lower_bound": [_safe_float(v) for v in forecast_df["yhat_lower"]],
            "upper_bound": [_safe_float(v) for v in forecast_df["yhat_upper"]],
        }

        arrow_new = pa.table({
            "ticker": pa.array(new_rows["ticker"], pa.string()),
            "horizon_months": pa.array(new_rows["horizon_months"], pa.int32()),
            "run_date": pa.array(new_rows["run_date"], pa.date32()),
            "forecast_date": pa.array(new_rows["forecast_date"], pa.date32()),
            "predicted_price": pa.array(new_rows["predicted_price"], pa.float64()),
            "lower_bound": pa.array(new_rows["lower_bound"], pa.float64()),
            "upper_bound": pa.array(new_rows["upper_bound"], pa.float64()),
        })

        if not existing.empty:
            arrow_existing = pa.Table.from_pandas(existing, schema=arrow_new.schema,
                                                  preserve_index=False)
            combined = pa.concat_tables([arrow_existing, arrow_new])
            tbl = self._load_table(_FORECASTS)
            tbl.overwrite(combined)
        else:
            self._append_rows(_FORECASTS, arrow_new)

        _logger.debug(
            "forecast_series inserted for %s %dm run %s (%d rows)",
            ticker, horizon_months, run_date, len(forecast_df),
        )

    def get_latest_forecast_series(
        self, ticker: str, horizon_months: int
    ) -> pd.DataFrame:
        """Return the forecast series from the most recent run for *ticker*.

        Args:
            ticker: Stock ticker symbol.
            horizon_months: Forecast horizon (3, 6, or 9).

        Returns:
            DataFrame with columns: forecast_date, predicted_price,
            lower_bound, upper_bound — sorted by forecast_date.
        """
        df = self._table_to_df(_FORECASTS)
        if df.empty:
            return df
        df = df[
            (df["ticker"] == ticker.upper()) &
            (df["horizon_months"] == int(horizon_months))
        ]
        if df.empty:
            return df
        latest_run = df["run_date"].max()
        return (
            df[df["run_date"] == latest_run]
            .sort_values("forecast_date")
            .reset_index(drop=True)
        )
