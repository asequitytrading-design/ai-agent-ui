"""Conversation context for multi-turn awareness.

Tracks current topic, rolling summary, and session
metadata. In-memory store with TTL-based eviction
and PostgreSQL persistence for cross-session resume.
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
    user_id: str = ""
    current_topic: str = ""
    last_agent: str = ""
    last_intent: str = ""
    summary: str = ""
    last_response: str = ""
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


# ── PG persistence helpers (asyncpg + NullPool) ─────

def _run_async(coro):
    """Run async coroutine from sync context.

    Offloads to a new thread when inside uvicorn's
    running event loop.
    """
    import asyncio
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
        ) as pool:
            return pool.submit(
                asyncio.run, coro,
            ).result(timeout=10)
    return asyncio.run(coro)


def _get_async_engine():
    """Create a disposable async NullPool engine."""
    from sqlalchemy.ext.asyncio import (
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool

    from config import get_settings

    return create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
    )


def _row_to_ctx(row) -> ConversationContext:
    """Convert a PG row to ConversationContext."""
    return ConversationContext(
        session_id=row.session_id,
        user_id=row.user_id or "",
        current_topic=row.current_topic or "",
        last_agent=row.last_agent or "",
        last_intent=row.last_intent or "",
        summary=row.summary or "",
        last_response=row.last_response or "",
        tickers_mentioned=(
            list(row.tickers_mentioned or [])
        ),
        user_tickers=(
            list(row.user_tickers or [])
        ),
        market_preference=(
            row.market_preference or ""
        ),
        subscription_tier=(
            row.subscription_tier or ""
        ),
        turn_count=row.turn_count or 0,
        last_updated=row.last_updated or 0.0,
    )


def _pg_load(
    session_id: str,
) -> ConversationContext | None:
    """Load context from PG (async NullPool)."""
    try:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
        )

        from db.models.conversation_context import (
            ConversationContextRow,
        )

        async def _load():
            eng = _get_async_engine()
            async with AsyncSession(eng) as sess:
                row = (
                    await sess.execute(
                        select(
                            ConversationContextRow,
                        ).where(
                            ConversationContextRow
                            .session_id == session_id,
                        ),
                    )
                ).scalar_one_or_none()
            await eng.dispose()
            if row is None:
                return None
            return _row_to_ctx(row)

        return _run_async(_load())
    except Exception:
        _logger.debug(
            "PG context load failed for %s",
            session_id,
            exc_info=True,
        )
        return None


def _pg_save(ctx: ConversationContext) -> None:
    """Persist context to PG (async NullPool).

    Uses INSERT ... ON CONFLICT UPDATE (upsert).
    """
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
        )

        async def _save():
            eng = _get_async_engine()
            async with AsyncSession(eng) as sess:
                await sess.execute(
                    text("""
INSERT INTO conversation_contexts (
    session_id, user_id, current_topic,
    last_agent, last_intent, summary,
    last_response, tickers_mentioned,
    user_tickers, market_preference,
    subscription_tier, turn_count,
    last_updated, updated_at
) VALUES (
    :session_id, :user_id, :current_topic,
    :last_agent, :last_intent, :summary,
    :last_response, :tickers_mentioned,
    :user_tickers, :market_preference,
    :subscription_tier, :turn_count,
    :last_updated, now()
)
ON CONFLICT (session_id) DO UPDATE SET
    current_topic = EXCLUDED.current_topic,
    last_agent = EXCLUDED.last_agent,
    last_intent = EXCLUDED.last_intent,
    summary = EXCLUDED.summary,
    last_response = EXCLUDED.last_response,
    tickers_mentioned = EXCLUDED.tickers_mentioned,
    user_tickers = EXCLUDED.user_tickers,
    market_preference = EXCLUDED.market_preference,
    subscription_tier = EXCLUDED.subscription_tier,
    turn_count = EXCLUDED.turn_count,
    last_updated = EXCLUDED.last_updated,
    updated_at = now()
"""),
                    {
                        "session_id": ctx.session_id,
                        "user_id": ctx.user_id,
                        "current_topic": (
                            ctx.current_topic
                        ),
                        "last_agent": ctx.last_agent,
                        "last_intent": ctx.last_intent,
                        "summary": ctx.summary,
                        "last_response": (
                            ctx.last_response[:500]
                        ),
                        "tickers_mentioned": (
                            ctx.tickers_mentioned
                        ),
                        "user_tickers": (
                            ctx.user_tickers
                        ),
                        "market_preference": (
                            ctx.market_preference
                        ),
                        "subscription_tier": (
                            ctx.subscription_tier
                        ),
                        "turn_count": ctx.turn_count,
                        "last_updated": (
                            ctx.last_updated
                        ),
                    },
                )
                await sess.commit()
            await eng.dispose()

        _run_async(_save())
        _logger.info(
            "PG context saved for %s "
            "(agent=%s, turns=%d)",
            ctx.session_id,
            ctx.last_agent,
            ctx.turn_count,
        )
    except Exception:
        _logger.warning(
            "PG context save failed for %s",
            ctx.session_id,
            exc_info=True,
        )


def _pg_load_latest_for_user(
    user_id: str,
) -> ConversationContext | None:
    """Load the most recent context for a user.

    Used when the frontend sends a new session_id but
    we want to resume from the last conversation.
    """
    try:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
        )

        from db.models.conversation_context import (
            ConversationContextRow,
        )

        async def _load():
            eng = _get_async_engine()
            async with AsyncSession(eng) as sess:
                row = (
                    await sess.execute(
                        select(
                            ConversationContextRow,
                        )
                        .where(
                            ConversationContextRow
                            .user_id == user_id,
                        )
                        .order_by(
                            ConversationContextRow
                            .updated_at.desc(),
                        )
                        .limit(1),
                    )
                ).scalar_one_or_none()
            await eng.dispose()
            if row is None:
                return None
            return _row_to_ctx(row)

        return _run_async(_load())
    except Exception:
        _logger.debug(
            "PG latest context load failed "
            "for %s",
            user_id,
            exc_info=True,
        )
        return None


class ConversationContextStore:
    """Thread-safe in-memory store with PG fallback."""

    def __init__(self, ttl: int = 3600) -> None:
        self._store: dict[str, ConversationContext] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def get(
        self, session_id: str,
    ) -> ConversationContext | None:
        with self._lock:
            ctx = self._store.get(session_id)
            if ctx is not None:
                age = time.time() - ctx.last_updated
                if age > self._ttl:
                    del self._store[session_id]
                    ctx = None
                else:
                    return ctx

        # Cache miss — try PG
        if ctx is None:
            ctx = _pg_load(session_id)
            if ctx is not None:
                with self._lock:
                    self._store[session_id] = ctx
        return ctx

    def get_latest_for_user(
        self, user_id: str,
    ) -> ConversationContext | None:
        """Get most recent context for a user.

        Checks in-memory first, falls back to PG.
        """
        with self._lock:
            best = None
            for ctx in self._store.values():
                if ctx.user_id != user_id:
                    continue
                if (
                    best is None
                    or ctx.last_updated
                    > best.last_updated
                ):
                    best = ctx
            if best is not None:
                return best

        return _pg_load_latest_for_user(user_id)

    def upsert(
        self,
        session_id: str,
        ctx: ConversationContext,
    ) -> None:
        with self._lock:
            if ctx.last_updated == 0.0:
                ctx.last_updated = time.time()
            self._store[session_id] = ctx

        # Persist to PG (best-effort)
        try:
            _pg_save(ctx)
        except Exception:
            _logger.warning(
                "PG save failed for %s",
                ctx.session_id,
                exc_info=True,
            )

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

_SUMMARY_PROMPT = (
    "Update this conversation summary given the "
    "latest exchange. Keep it under 3 sentences. "
    "Include: topic discussed, key tickers/numbers "
    "mentioned, and any conclusions.\n\n"
    "Previous summary: {prev}\n"
    "User asked: {user_input}\n"
    "Assistant answered: {response}\n\n"
    "Updated summary:"
)


def _get_summary_llm():
    """Get cheapest available LLM for summarization.

    Cascade: Ollama → Groq scout → Groq versatile.
    Returns None if all unavailable.
    """
    try:
        from config import get_settings
        from llm_fallback import FallbackLLM
        from message_compressor import (
            MessageCompressor,
        )
        from token_budget import get_token_budget

        s = get_settings()
        tiers = [
            t.strip()
            for t in s.groq_model_tiers.split(",")
            if t.strip()
        ][:2]
        ollama = (
            s.ollama_model if s.ollama_enabled
            else None
        )
        from observability import (
            get_obs_collector,
        )

        return FallbackLLM(
            groq_models=tiers,
            anthropic_model=None,
            temperature=0,
            agent_id="summary",
            token_budget=get_token_budget(),
            compressor=MessageCompressor(),
            obs_collector=get_obs_collector(),
            cascade_profile="tool",
            ollama_model=ollama,
            ollama_first=True,
        )
    except Exception:
        return None


def update_summary(
    ctx: ConversationContext,
    user_input: str,
    response: str,
) -> None:
    """Update rolling summary in-place.

    Increments turn_count regardless of LLM availability.
    """
    ctx.turn_count += 1

    llm = _get_summary_llm()
    if llm is None:
        _logger.debug("No LLM for summary update")
        return

    from langchain_core.messages import HumanMessage

    prompt = _SUMMARY_PROMPT.format(
        prev=ctx.summary or "No previous context.",
        user_input=user_input[:300],
        response=response[:500],
    )

    try:
        result = llm.invoke(
            [HumanMessage(content=prompt)],
        )
        text = (
            result.content
            if hasattr(result, "content")
            else str(result)
        ).strip()
        if text:
            ctx.summary = text
    except Exception:
        _logger.debug(
            "Summary update failed",
            exc_info=True,
        )
