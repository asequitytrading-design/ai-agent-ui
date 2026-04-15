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
