"""Reference test for the EMV-14 indicator helper (AA-12).

Verifies that
:func:`backend.tools._analysis_indicators.compute_emv_14`
produces a correctly-shaped, NaN-safe series and that the
SMA-14 smoothing emits ``NaN`` during the warm-up window
(t < 14) as expected.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.tools._analysis_indicators import compute_emv_14


def _make_ohlcv(rows: int = 30) -> pd.DataFrame:
    """Synthetic monotonic OHLCV: deterministic for the
    EMV reference computation."""
    idx = pd.RangeIndex(rows)
    high = pd.Series([100.0 + i * 0.5 for i in range(rows)], index=idx)
    low = pd.Series([99.0 + i * 0.5 for i in range(rows)], index=idx)
    volume = pd.Series([1_000_000 + i * 1000 for i in range(rows)], index=idx)
    return pd.DataFrame({"High": high, "Low": low, "Volume": volume})


def test_compute_emv_14_returns_series_aligned_to_input():
    df = _make_ohlcv(30)
    out = compute_emv_14(df)
    assert isinstance(out, pd.Series)
    assert len(out) == len(df)
    # SMA-14: the first 13 windows are NaN, then a real value.
    assert math.isnan(out.iloc[0])
    assert math.isnan(out.iloc[12])
    assert not math.isnan(out.iloc[14])
    assert not math.isnan(out.iloc[29])


def test_compute_emv_14_handles_empty_dataframe():
    out = compute_emv_14(pd.DataFrame({"High": [], "Low": [], "Volume": []}))
    assert out.empty


def test_compute_emv_14_handles_zero_range_candles():
    """High == Low → div-by-zero in the EMV box ratio.
    Helper must coerce those rows to NaN, not ±inf."""
    df = _make_ohlcv(30)
    df.loc[0:3, "Low"] = df.loc[0:3, "High"]  # 4 zero-range bars
    out = compute_emv_14(df)
    # No infinities should leak into the smoothed series.
    assert not np.isinf(out.dropna()).any()


def test_compute_emv_14_raises_on_missing_columns():
    with pytest.raises(ValueError, match="missing columns"):
        compute_emv_14(pd.DataFrame({"High": [1.0]}))


def test_compute_emv_14_t14_value_is_finite_and_signed():
    """For a monotonically rising synthetic series the EMV
    midpoint move is positive ⇒ EMV is finite and positive."""
    df = _make_ohlcv(30)
    out = compute_emv_14(df)
    sample = out.iloc[14]
    assert math.isfinite(sample)
    assert sample > 0
