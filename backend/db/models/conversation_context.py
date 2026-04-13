"""ConversationContext ORM model — PG persistence
for cross-session chat context resumption."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    JSONB,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class ConversationContextRow(Base):
    """Persisted conversation context per session.

    One row per ``session_id``.  Updated after every
    chat turn so that context survives backend restarts
    and can be resumed in a new browser session.
    """

    __tablename__ = "conversation_contexts"

    session_id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )
    current_topic: Mapped[str] = mapped_column(
        Text, default="",
    )
    last_agent: Mapped[str] = mapped_column(
        String(64), default="",
    )
    last_intent: Mapped[str] = mapped_column(
        String(64), default="",
    )
    summary: Mapped[str] = mapped_column(
        Text, default="",
    )
    last_response: Mapped[str] = mapped_column(
        Text, default="",
    )
    tickers_mentioned: Mapped[list] = mapped_column(
        ARRAY(String(20)), default=list,
    )
    user_tickers: Mapped[list] = mapped_column(
        ARRAY(String(20)), default=list,
    )
    market_preference: Mapped[str] = mapped_column(
        String(20), default="",
    )
    subscription_tier: Mapped[str] = mapped_column(
        String(20), default="",
    )
    turn_count: Mapped[int] = mapped_column(
        Integer, default=0,
    )
    last_updated: Mapped[float] = mapped_column(
        Float, default=0.0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
