"""Volatility regime classification for Prophet forecast tuning.

Classifies a ticker into one of three regimes based on annualized
volatility, then provides matching Prophet constructor config and
logistic growth bounds.

Regime table
------------
Regime    | Ann. Vol   | Growth   | Transform | cps  | cp_range
----------|------------|----------|-----------|------|----------
stable    | < 30 %     | linear   | none      | 0.01 | 0.80
moderate  | 30–60 %    | linear   | log(y)    | 0.10 | 0.85
volatile  | ≥ 60 %     | logistic | log(y)    | 0.25 | 0.90

Boundaries are inclusive on the upper regime:
  30.0 → moderate,  60.0 → volatile.

None/missing volatility defaults to "moderate".

Notes
-----
- ``build_prophet_config`` returns only Prophet constructor kwargs.
  ``cap``/``floor`` belong on the DataFrame (add them before fitting).
- ``compute_logistic_bounds`` returns (cap, floor) from raw OHLCV.
"""

import logging
from dataclasses import dataclass

import pandas as pd

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STABLE_UPPER = 30.0   # < 30 → stable
_MODERATE_UPPER = 60.0  # 30–59.99 → moderate; ≥ 60 → volatile

_REGIMES = ("stable", "moderate", "volatile")

# Prophet constructor kwargs per regime.
_REGIME_CONFIG: dict[str, dict] = {
    "stable": {
        "growth": "linear",
        "changepoint_prior_scale": 0.01,
        "changepoint_range": 0.80,
    },
    "moderate": {
        "growth": "linear",
        "changepoint_prior_scale": 0.10,
        "changepoint_range": 0.85,
    },
    "volatile": {
        "growth": "logistic",
        "changepoint_prior_scale": 0.25,
        "changepoint_range": 0.90,
    },
}

# Look-back windows (trading days).
_TWO_YEAR_DAYS = 504
_ONE_YEAR_DAYS = 252


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeConfig:
    """Immutable snapshot of a regime classification result.

    Attributes
    ----------
    regime:
        One of ``"stable"``, ``"moderate"``, ``"volatile"``.
    growth:
        Prophet ``growth`` param (``"linear"`` or ``"logistic"``).
    transform:
        y-transform to apply before fitting
        (``"none"`` or ``"log"``).
    changepoint_prior_scale:
        Prophet ``changepoint_prior_scale``.
    changepoint_range:
        Prophet ``changepoint_range``.
    """

    regime: str
    growth: str
    transform: str
    changepoint_prior_scale: float
    changepoint_range: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_regime(annualized_vol: float | None) -> str:
    """Return the volatility regime for *annualized_vol*.

    Parameters
    ----------
    annualized_vol:
        Annualized volatility as a percentage (e.g. 25.0 = 25 %).
        Pass ``None`` to get the default ("moderate").

    Returns
    -------
    str
        One of ``"stable"``, ``"moderate"``, ``"volatile"``.
    """
    if annualized_vol is None:
        _logger.debug(
            "annualized_vol is None — defaulting to 'moderate'"
        )
        return "moderate"

    vol = float(annualized_vol)
    if vol < _STABLE_UPPER:
        return "stable"
    if vol < _MODERATE_UPPER:
        return "moderate"
    return "volatile"


def compute_logistic_bounds(
    ohlcv_df: pd.DataFrame,
) -> tuple[float, float]:
    """Compute logistic cap and floor from OHLCV history.

    cap   = all-time-high over the last 2 years × 1.5
    floor = 52-week (1 year) low × 0.3

    Parameters
    ----------
    ohlcv_df:
        DataFrame with at least ``high`` and ``low`` columns,
        ordered chronologically. Must contain ≥ 1 row.

    Returns
    -------
    (cap, floor) : tuple[float, float]
    """
    two_yr = ohlcv_df["high"].iloc[-_TWO_YEAR_DAYS:]
    one_yr = ohlcv_df["low"].iloc[-_ONE_YEAR_DAYS:]

    ath_2yr = float(two_yr.max())
    low_1yr = float(one_yr.min())

    cap = ath_2yr * 1.5
    floor = low_1yr * 0.3

    _logger.debug(
        "Logistic bounds: cap=%.2f (ATH %.2f × 1.5), "
        "floor=%.2f (1yr_low %.2f × 0.3)",
        cap, ath_2yr, floor, low_1yr,
    )
    return cap, floor


def build_prophet_config(regime: str) -> dict:
    """Return Prophet constructor kwargs for *regime*.

    Parameters
    ----------
    regime:
        One of ``"stable"``, ``"moderate"``, ``"volatile"``.

    Returns
    -------
    dict
        Kwargs suitable for ``Prophet(**build_prophet_config(regime))``.
        Does NOT include ``cap`` or ``floor`` — add those to the
        DataFrame before fitting.

    Raises
    ------
    ValueError
        If *regime* is not a recognised value.
    """
    if regime not in _REGIME_CONFIG:
        raise ValueError(
            f"Unknown regime {regime!r}. "
            f"Expected one of {_REGIMES}."
        )
    # Return a shallow copy so callers cannot mutate the constant.
    return dict(_REGIME_CONFIG[regime])


def get_regime_config(
    annualized_vol: float | None,
) -> RegimeConfig:
    """Classify volatility and return a full :class:`RegimeConfig`.

    Convenience wrapper around :func:`classify_regime` and
    :func:`build_prophet_config` for callers that need a single
    structured result.

    Parameters
    ----------
    annualized_vol:
        Annualized volatility in percent, or ``None``.

    Returns
    -------
    RegimeConfig
    """
    regime = classify_regime(annualized_vol)
    cfg = _REGIME_CONFIG[regime]
    transform = "none" if regime == "stable" else "log"
    return RegimeConfig(
        regime=regime,
        growth=cfg["growth"],
        transform=transform,
        changepoint_prior_scale=cfg["changepoint_prior_scale"],
        changepoint_range=cfg["changepoint_range"],
    )
