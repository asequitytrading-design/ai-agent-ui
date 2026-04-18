"""Market detection utility — single source of truth.

Every module that needs to classify a ticker as ``india``
or ``us`` MUST import from here.  Do NOT add local
suffix-check helpers elsewhere.
"""


# Indian index tickers (no .NS suffix but trade on
# NSE/BSE).  Used by detect_market() to avoid
# misclassifying them as "us".
_INDIAN_INDEX_TICKERS = frozenset((
    "^NSEI",      # Nifty 50
    "^BSESN",     # Sensex
    "^INDIAVIX",  # India VIX
))


def detect_market(
    ticker: str,
    registry_market: str | None = None,
) -> str:
    """Return ``'india'`` or ``'us'``.

    Priority:
        1. ``.NS`` / ``.BO`` suffix → ``'india'``
        2. Known Indian index tickers → ``'india'``
        3. *registry_market* in ``(NSE, BSE, INDIA)``
           → ``'india'``
        4. Default → ``'us'``
    """
    if ticker.endswith((".NS", ".BO")):
        return "india"
    if ticker in _INDIAN_INDEX_TICKERS:
        return "india"
    if registry_market and registry_market.upper() in (
        "NSE", "BSE", "INDIA",
    ):
        return "india"
    return "us"


def detect_currency(market: str) -> str:
    """Return ``'INR'`` or ``'USD'`` from *market*."""
    return "INR" if market == "india" else "USD"


def is_indian_market(
    ticker: str,
    registry_market: str | None = None,
) -> bool:
    """Convenience: True when *ticker* is Indian."""
    return detect_market(ticker, registry_market) == "india"


def safe_str(val) -> str | None:
    """Return a clean string or ``None``.

    Handles the three broken paths that bite this project:

    * ``None`` → ``None``
    * pandas/numpy ``float('nan')`` → ``None`` (NaN is
      *truthy* in Python so ``x or fallback`` silently
      keeps it)
    * empty / whitespace-only string → ``None``

    Use this wherever you read optional string fields from
    Iceberg rows (sector, industry, company_name,
    currency, ...). ETFs and indices return NaN for
    ``company_info.sector``, and mixing NaN into labels,
    prompts, or groupby keys corrupts downstream logic.
    """
    if val is None:
        return None
    # pandas NaN is a float. Checking isinstance(float)
    # first avoids importing pandas for non-numeric
    # values.
    if isinstance(val, float):
        import math

        if math.isnan(val):
            return None
        return str(val)
    if isinstance(val, str):
        stripped = val.strip()
        return stripped or None
    try:
        return str(val)
    except Exception:  # noqa: BLE001
        return None


def safe_sector(
    val,
    fallback: str = "Other",
) -> str:
    """Return a non-empty sector label.

    Thin wrapper around :func:`safe_str` that always
    returns a string so it's safe to use as a dict key,
    groupby key, or prompt token.  Pass a custom
    *fallback* (e.g. ``"ETF"``) where that makes more
    sense than ``"Other"``.
    """
    cleaned = safe_str(val)
    return cleaned if cleaned else fallback
