"""Pre-warm Redis cache on backend startup.

Populates shared (non-user-scoped) cache keys so that the
very first page load serves from Redis instead of scanning
Iceberg.  Per-ticker chart data is warmed in a background
thread to avoid delaying server readiness.

Usage::

    # In routes.py lifespan:
    from cache_warmup import warm_shared, warm_tickers

    warm_shared()                    # blocking, < 1 s
    threading.Thread(
        target=warm_tickers,
        daemon=True,
    ).start()                        # background
"""

from __future__ import annotations

import json
import logging
import time

_logger = logging.getLogger(__name__)


def warm_shared() -> None:
    """Warm shared (non-user-scoped) cache keys.

    Currently warms:
    - ``cache:dash:registry`` — all registered tickers
    - ``cache:admin:audit`` — audit event log

    Runs synchronously; typically completes in < 1 s.
    """
    from cache import get_cache, TTL_STABLE, TTL_VOLATILE

    cache = get_cache()
    if not cache.ping():
        _logger.info(
            "cache_warmup: Redis unavailable; "
            "skipping warm-up.",
        )
        return

    t0 = time.monotonic()
    warmed = 0

    # ── Registry ──────────────────────────────────
    try:
        from tools._stock_shared import _require_repo

        stock_repo = _require_repo()
        registry = stock_repo.get_all_registry()

        if registry:
            from dashboard_models import (
                RegistryResponse,
                RegistryTicker,
            )

            items = []
            for ticker, meta in registry.items():
                mkt = "india" if (
                    ticker.endswith(".NS")
                    or ticker.endswith(".BO")
                ) else "us"
                ccy = "INR" if mkt == "india" else "USD"
                items.append(
                    RegistryTicker(
                        ticker=ticker,
                        company_name=None,
                        market=mkt,
                        currency=ccy,
                        current_price=None,
                        last_fetch_date=(
                            meta.get(
                                "last_fetch_date", ""
                            ) or None
                        ),
                    )
                )
            items.sort(key=lambda t: t.ticker)
            result = RegistryResponse(tickers=items)
            cache.set(
                "cache:dash:registry",
                result.model_dump_json(),
                TTL_STABLE,
            )
            warmed += 1
    except Exception:
        _logger.warning(
            "cache_warmup: registry failed",
            exc_info=True,
        )

    # ── Audit log ─────────────────────────────────
    try:
        import auth.endpoints.helpers as _helpers

        repo = _helpers._get_repo()
        raw = repo.list_audit_events()
        events = []
        for ev in raw:
            d = dict(ev)
            ts = d.get("event_timestamp")
            if ts is not None and hasattr(
                ts, "isoformat"
            ):
                d["event_timestamp"] = ts.isoformat()
            events.append(d)
        cache.set(
            "cache:admin:audit",
            json.dumps({"events": events}),
            TTL_VOLATILE,
        )
        warmed += 1
    except Exception:
        _logger.warning(
            "cache_warmup: audit log failed",
            exc_info=True,
        )

    elapsed = (time.monotonic() - t0) * 1000
    _logger.info(
        "cache_warmup: warmed %d shared keys "
        "in %.0f ms",
        warmed,
        elapsed,
    )


def warm_tickers() -> None:
    """Warm per-ticker chart cache keys in background.

    Iterates over all registered tickers and populates:
    - ``cache:chart:ohlcv:{ticker}``
    - ``cache:chart:indicators:{ticker}``

    Runs in a daemon thread; errors are logged but
    never propagate.
    """
    from cache import get_cache, TTL_STABLE

    cache = get_cache()
    if not cache.ping():
        return

    t0 = time.monotonic()
    warmed = 0

    try:
        from tools._stock_shared import _require_repo
        from dashboard_models import (
            OHLCVPoint,
            OHLCVResponse,
            IndicatorPoint,
            IndicatorsResponse,
        )

        stock_repo = _require_repo()
        registry = stock_repo.get_all_registry()
        tickers = list(registry.keys())

        for ticker in tickers:
            try:
                # OHLCV
                ck = f"cache:chart:ohlcv:{ticker}"
                if cache.get(ck) is None:
                    df = stock_repo.get_ohlcv(ticker)
                    if not df.empty:
                        points = [
                            OHLCVPoint(
                                date=str(r["date"]),
                                open=float(r["open"]),
                                high=float(r["high"]),
                                low=float(r["low"]),
                                close=float(
                                    r["close"]
                                ),
                                volume=int(
                                    r["volume"]
                                ),
                            )
                            for _, r in (
                                df.iterrows()
                            )
                        ]
                        result = OHLCVResponse(
                            ticker=ticker,
                            data=points,
                        )
                        cache.set(
                            ck,
                            result.model_dump_json(),
                            TTL_STABLE,
                        )
                        warmed += 1
            except Exception:
                _logger.debug(
                    "cache_warmup: ohlcv %s failed",
                    ticker,
                )

            try:
                # Indicators
                ck = (
                    f"cache:chart:indicators:"
                    f"{ticker}"
                )
                if cache.get(ck) is None:
                    df = (
                        stock_repo
                        .get_technical_indicators(
                            ticker,
                        )
                    )
                    if not df.empty:
                        pts = []
                        for _, r in df.iterrows():
                            pts.append(
                                IndicatorPoint(
                                    date=str(
                                        r.get(
                                            "date",
                                            "",
                                        )
                                    ),
                                    sma_50=_sf(
                                        r.get(
                                            "sma_50"
                                        )
                                    ),
                                    sma_200=_sf(
                                        r.get(
                                            "sma_200"
                                        )
                                    ),
                                    ema_20=_sf(
                                        r.get(
                                            "ema_20"
                                        )
                                    ),
                                    rsi_14=_sf(
                                        r.get(
                                            "rsi_14"
                                        )
                                    ),
                                    macd=_sf(
                                        r.get("macd")
                                    ),
                                    macd_signal=_sf(
                                        r.get(
                                            "macd_signal"
                                        )
                                    ),
                                    macd_hist=_sf(
                                        r.get(
                                            "macd_hist"
                                        )
                                    ),
                                    bb_upper=_sf(
                                        r.get(
                                            "bb_upper"
                                        )
                                    ),
                                    bb_lower=_sf(
                                        r.get(
                                            "bb_lower"
                                        )
                                    ),
                                )
                            )
                        result = IndicatorsResponse(
                            ticker=ticker,
                            data=pts,
                        )
                        cache.set(
                            ck,
                            result.model_dump_json(),
                            TTL_STABLE,
                        )
                        warmed += 1
            except Exception:
                _logger.debug(
                    "cache_warmup: indicators"
                    " %s failed",
                    ticker,
                )

    except Exception:
        _logger.warning(
            "cache_warmup: ticker warm-up failed",
            exc_info=True,
        )

    elapsed = (time.monotonic() - t0) * 1000
    _logger.info(
        "cache_warmup: warmed %d ticker keys "
        "in %.0f ms",
        warmed,
        elapsed,
    )


def _sf(val) -> float | None:
    """Safe float conversion."""
    if val is None:
        return None
    try:
        import math

        f = float(val)
        return None if math.isnan(f) else round(f, 4)
    except (ValueError, TypeError):
        return None
