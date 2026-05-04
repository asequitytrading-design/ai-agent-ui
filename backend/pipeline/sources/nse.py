"""NSE data source using jugaad-data."""

from __future__ import annotations

import asyncio
import io
import logging
import types
from datetime import date
from functools import partial

import pandas as pd
from jugaad_data.nse import full_bhavcopy_raw, stock_df

from backend.pipeline.sources.base import (
    SourceError,
    SourceErrorCategory,
    classify_error,
)

_logger = logging.getLogger(__name__)

# Column mapping from jugaad-data to standard names.
# jugaad-data column names can vary; we handle both
# uppercase and mixed-case variants defensively.
_COLUMN_MAP = types.MappingProxyType(
    {
        "DATE": "date",
        "OPEN": "open",
        "HIGH": "high",
        "LOW": "low",
        "CLOSE": "adj_close",
        "LTP": "close",
        "VOLUME": "volume",
        # Lowercase variants
        "date": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "adj_close",
        "ltp": "close",
        "volume": "volume",
        # Title-case variants
        "Date": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "adj_close",
        "Ltp": "close",
        "Volume": "volume",
    }
)

_REQUIRED_COLS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
]

# NSE full bhavcopy CSV columns (sec_bhavdata_full_*).
# Names sometimes carry leading whitespace from NSE; we
# strip in ``_normalise_bhavcopy``.
_BHAV_REQUIRED_COLS = [
    "SYMBOL",
    "SERIES",
    "DATE1",
    "TTL_TRD_QNTY",
    "TURNOVER_LACS",
    "DELIV_QTY",
    "DELIV_PER",
]
_BHAV_OUT_COLS = [
    "ticker",
    "date",
    "deliverable_qty",
    "delivery_pct",
    "traded_qty",
    "traded_value",
]


class NseSource:
    """Fetches OHLCV data from NSE via jugaad-data.

    Accepts plain NSE symbols (e.g. ``RELIANCE``, no
    ``.NS`` suffix).  The synchronous ``stock_df`` call is
    run in a thread-pool executor.
    """

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV from NSE for *symbol*."""
        if start is None or end is None:
            raise SourceError(
                SourceErrorCategory.UNKNOWN,
                f"NseSource requires both start and end "
                f"dates for {symbol}",
            )

        loop = asyncio.get_running_loop()
        try:
            df: pd.DataFrame = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    partial(
                        stock_df,
                        symbol=symbol,
                        from_date=start,
                        to_date=end,
                    ),
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            raise SourceError(
                SourceErrorCategory.TIMEOUT,
                f"NSE fetch timed out for {symbol} " f"(60s limit)",
            )
        except Exception as exc:
            cat = classify_error(exc)
            raise SourceError(
                cat,
                f"NSE fetch failed for {symbol}: {exc}",
                original=exc,
            ) from exc

        df = self._normalise_columns(df, symbol)
        _logger.debug(
            "NseSource fetched %d rows for %s",
            len(df),
            symbol,
        )
        return df

    # --------------------------------------------------
    @staticmethod
    def _normalise_columns(
        df: pd.DataFrame,
        symbol: str,
    ) -> pd.DataFrame:
        """Map jugaad-data columns to standard names."""
        rename = {}
        for col in df.columns:
            if col in _COLUMN_MAP:
                rename[col] = _COLUMN_MAP[col]

        df = df.rename(columns=rename)

        # If adj_close present but close missing, copy it.
        if "adj_close" in df.columns and "close" not in df.columns:
            df["close"] = df["adj_close"]

        # If close present but adj_close missing, copy it.
        if "close" in df.columns and "adj_close" not in df.columns:
            df["adj_close"] = df["close"]

        missing = [c for c in _REQUIRED_COLS if c not in df.columns]
        if missing:
            raise SourceError(
                SourceErrorCategory.PARSE_ERROR,
                f"NSE data for {symbol} missing columns: " f"{missing}",
            )

        return df[_REQUIRED_COLS].copy()

    # --------------------------------------------------
    # Full bhavcopy (delivery + price for whole exchange)
    # --------------------------------------------------
    async def fetch_bhavcopy(self, d: date) -> pd.DataFrame:
        """Fetch NSE full bhavcopy for *d* (delivery + price).

        One HTTP call returns price + volume + delivery
        for every NSE-listed equity for the trading day —
        used by Sprint 9 Advanced Analytics to populate
        ``stocks.nse_delivery``.

        Args:
            d: Trading date.  Weekends and market holidays
                will return an empty frame (the call may
                also raise ``SourceError`` for older dates
                where bhavcopy is no longer hosted).

        Returns:
            DataFrame with columns ``ticker`` (``.NS``
            suffix), ``date`` (``datetime.date``),
            ``deliverable_qty``, ``delivery_pct``,
            ``traded_qty``, ``traded_value``.  Filtered
            to the equity series (``EQ``) only.
        """
        loop = asyncio.get_running_loop()
        try:
            text: str = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    partial(full_bhavcopy_raw, d),
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            raise SourceError(
                SourceErrorCategory.TIMEOUT,
                f"NSE bhavcopy fetch timed out for {d} " f"(60s limit)",
            )
        except Exception as exc:
            cat = classify_error(exc)
            raise SourceError(
                cat,
                f"NSE bhavcopy fetch failed for {d}: {exc}",
                original=exc,
            ) from exc

        if not text or not text.strip():
            _logger.info(
                "NSE bhavcopy empty body for %s " "(market holiday?)",
                d,
            )
            return pd.DataFrame(columns=_BHAV_OUT_COLS)

        try:
            df = pd.read_csv(io.StringIO(text))
        except Exception as exc:
            raise SourceError(
                SourceErrorCategory.PARSE_ERROR,
                f"NSE bhavcopy CSV parse failed for {d}: " f"{exc}",
                original=exc,
            ) from exc

        return self._normalise_bhavcopy(df, d)

    @staticmethod
    def _normalise_bhavcopy(
        df: pd.DataFrame,
        d: date,
    ) -> pd.DataFrame:
        """Filter + project NSE bhavcopy CSV to our schema.

        Strips column whitespace (NSE prepends spaces to
        every column except SYMBOL), filters to the EQ
        series, and projects to the
        ``stocks.nse_delivery`` schema with ``.NS``
        suffix on ticker.

        Args:
            df: DataFrame parsed from full bhavcopy CSV.
            d: Trading date (used in error messages).

        Returns:
            Projected DataFrame matching ``_BHAV_OUT_COLS``.
            Empty if no equity rows.

        Raises:
            SourceError: Required columns are missing.
        """
        df.columns = [str(c).strip() for c in df.columns]

        missing = [c for c in _BHAV_REQUIRED_COLS if c not in df.columns]
        if missing:
            raise SourceError(
                SourceErrorCategory.PARSE_ERROR,
                f"NSE bhavcopy {d} missing columns: " f"{missing}",
            )

        # Filter to equity series (drops BE/BZ/SM/etc).
        series = df["SERIES"].astype(str).str.strip()
        df = df[series == "EQ"].copy()
        if df.empty:
            return pd.DataFrame(columns=_BHAV_OUT_COLS)

        symbol = df["SYMBOL"].astype(str).str.strip()
        try:
            parsed_date = pd.to_datetime(
                df["DATE1"].astype(str).str.strip(),
                format="%d-%b-%Y",
            ).dt.date
        except Exception as exc:
            raise SourceError(
                SourceErrorCategory.PARSE_ERROR,
                f"NSE bhavcopy {d} DATE1 parse failed: " f"{exc}",
                original=exc,
            ) from exc

        out = pd.DataFrame(
            {
                "ticker": symbol + ".NS",
                "date": parsed_date,
                "deliverable_qty": pd.to_numeric(
                    df["DELIV_QTY"],
                    errors="coerce",
                ),
                "delivery_pct": pd.to_numeric(
                    df["DELIV_PER"],
                    errors="coerce",
                ),
                "traded_qty": pd.to_numeric(
                    df["TTL_TRD_QNTY"],
                    errors="coerce",
                ),
                "traded_value": pd.to_numeric(
                    df["TURNOVER_LACS"],
                    errors="coerce",
                ),
            }
        )
        return out.reset_index(drop=True)
