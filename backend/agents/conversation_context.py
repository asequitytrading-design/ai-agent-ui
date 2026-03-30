"""Conversation context for multi-turn awareness.

Tracks current topic, rolling summary, and session
metadata. In-memory store with TTL-based eviction.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """Per-session conversation state."""

    session_id: str
    current_topic: str = ""
    last_agent: str = ""
    last_intent: str = ""
    summary: str = ""
    tickers_mentioned: list[str] = field(
        default_factory=list,
    )
    user_tickers: list[str] = field(
        default_factory=list,
    )
    market_preference: str = ""
    subscription_tier: str = ""
    turn_count: int = 0
    last_updated: float = 0.0


class ConversationContextStore:
    """Thread-safe in-memory store with TTL eviction."""

    def __init__(self, ttl: int = 3600) -> None:
        self._store: dict[str, ConversationContext] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def get(
        self, session_id: str,
    ) -> ConversationContext | None:
        with self._lock:
            ctx = self._store.get(session_id)
            if ctx is None:
                return None
            age = time.time() - ctx.last_updated
            if age > self._ttl:
                del self._store[session_id]
                return None
            return ctx

    def upsert(
        self,
        session_id: str,
        ctx: ConversationContext,
    ) -> None:
        with self._lock:
            if ctx.last_updated == 0.0:
                ctx.last_updated = time.time()
            self._store[session_id] = ctx

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                k for k, v in self._store.items()
                if now - v.last_updated > self._ttl
            ]
            for k in expired:
                del self._store[k]
            if expired:
                _logger.debug(
                    "Evicted %d expired contexts",
                    len(expired),
                )


# Module-level singleton.
context_store = ConversationContextStore()
