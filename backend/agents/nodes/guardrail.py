"""Finance-only guardrail node.

First node in the LangGraph supervisor graph.  Checks
content safety, determines if the query is financial,
and extracts ticker symbols.  Non-financial queries are
routed to the decline node.  Zero LLM cost.
"""

from __future__ import annotations

import logging
import re
import time

_logger = logging.getLogger(__name__)

from agents.router import (
    _STOCK_KEYWORDS,
    _TICKER_PATTERN,
    is_blocked,
)

# Additional financial keywords beyond _STOCK_KEYWORDS
# to improve classification accuracy.
_EXTRA_FINANCIAL: set[str] = {
    "portfolio",
    "holdings",
    "allocation",
    "weightage",
    "rebalance",
    "diversify",
    "profit",
    "loss",
    "pnl",
    "p&l",
    "capital gain",
    "capital loss",
    "gain",
    "yield",
    "beta",
    "alpha",
    "risk",
    "hedge",
    "margin",
    "leverage",
    "valuation",
    "outlook",
    "predict",
    "prophet",
    "technical",
    "fundamental",
    "indicator",
    "indicators",
    "screener",
    "correlation",
    "headline",
    "sentiment",
    "recommendation",
    "analyst",
    "upgrade",
    "downgrade",
    "overweight",
    "underweight",
}

_ALL_FINANCIAL = _STOCK_KEYWORDS | _EXTRA_FINANCIAL

# Common uppercase words that look like tickers but
# are not.  Extends the filter in router.py.
_COMMON_WORDS: set[str] = {
    "I", "A", "IT", "IS", "AM", "AN", "AT", "AS",
    "BE", "BY", "DO", "GO", "HE", "IF", "IN", "ME",
    "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO",
    "UP", "US", "WE", "THE", "AND", "FOR", "NOT",
    "BUT", "ALL", "CAN", "HER", "WAS", "ONE", "OUR",
    "OUT", "ARE", "HAS", "HIS", "HOW", "ITS", "MAY",
    "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "DID",
    "GET", "HIM", "LET", "SAY", "SHE", "TOO", "USE",
}


def guardrail(state: dict) -> dict:
    """Check if query is financial and extract tickers.

    Returns a dict with ``next_agent`` set to either
    ``"router"`` (financial) or ``"decline"``
    (non-financial or blocked).
    """
    user_input: str = state.get("user_input", "")

    # Record start time for latency tracking
    start_ns = time.monotonic_ns()

    # ── Query cache check ─────────────────────────
    try:
        from agents.nodes.query_cache import (
            check_cache,
        )

        cached = check_cache(user_input)
        if cached:
            return {
                "final_response": cached,
                "next_agent": "cache_hit",
                "start_time_ns": start_ns,
                "tool_events": [],
                "current_agent": "cache",
            }
    except Exception:
        pass  # cache check is best-effort

    # ── Content safety ──────────────────────────────
    if is_blocked(user_input):
        return {
            "next_agent": "decline",
            "error": "blocked",
            "start_time_ns": start_ns,
        }

    # ── Follow-up detection (BEFORE keyword gate) ───
    # Follow-ups like "which one should I increase?"
    # may lack financial keywords but are valid in
    # context. Must run before the relevance check.
    session_id = state.get("session_id", "")
    _followup_result = "new_topic"
    _ctx = None
    if session_id:
        try:
            from agents.conversation_context import (
                context_store,
            )
            from agents.nodes.topic_classifier import (
                classify_followup,
            )

            _ctx = context_store.get(session_id)
            _followup_result = classify_followup(
                user_input, _ctx,
            )
            if _followup_result == "follow_up" and _ctx:
                _logger.debug(
                    "Follow-up for session %s"
                    " — reusing agent=%s",
                    session_id,
                    _ctx.last_agent,
                )
        except Exception:
            _logger.debug(
                "Follow-up detection failed",
                exc_info=True,
            )

    # If follow-up with known agent, skip keyword
    # gate AND router — go straight to the agent.
    if (
        _followup_result == "follow_up"
        and _ctx
        and _ctx.last_agent
    ):
        return {
            "tickers": _ctx.tickers_mentioned,
            "next_agent": _ctx.last_agent,
            "intent": _ctx.last_intent,
            "start_time_ns": start_ns,
        }

    # ── Financial relevance ─────────────────────────
    lower = user_input.lower()
    tokens = set(re.findall(r"[a-z&]+", lower))

    # Strong keywords (unambiguous financial terms)
    strong = tokens & _STOCK_KEYWORDS
    # Weak keywords (could be financial or general)
    weak = tokens & _EXTRA_FINANCIAL

    # Check for ticker-like symbols
    raw_tickers = _TICKER_PATTERN.findall(user_input)
    tickers = [
        t for t in raw_tickers
        if t not in _COMMON_WORDS
    ]
    has_ticker = bool(tickers)

    # Financial if: strong keyword, or ticker found,
    # or 2+ weak keywords (reduces false positives
    # from single ambiguous words like "news").
    has_keyword = bool(
        strong or has_ticker or len(weak) >= 2
    )

    if not has_keyword and not has_ticker:
        return {
            "next_agent": "decline",
            "start_time_ns": start_ns,
        }

    return {
        "tickers": tickers,
        "next_agent": "router",
        "start_time_ns": start_ns,
    }
