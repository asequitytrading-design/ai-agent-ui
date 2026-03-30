"""Tests for ConversationContext and ContextStore."""

import time

import pytest

from agents.conversation_context import (
    ConversationContext,
    ConversationContextStore,
)


class TestConversationContext:
    def test_default_values(self):
        ctx = ConversationContext(session_id="s1")
        assert ctx.session_id == "s1"
        assert ctx.current_topic == ""
        assert ctx.summary == ""
        assert ctx.turn_count == 0
        assert ctx.tickers_mentioned == []

    def test_update_fields(self):
        ctx = ConversationContext(session_id="s1")
        ctx.current_topic = "AAPL sentiment"
        ctx.turn_count = 3
        ctx.tickers_mentioned = ["AAPL"]
        assert ctx.current_topic == "AAPL sentiment"
        assert ctx.turn_count == 3


class TestConversationContextStore:
    def test_get_missing_returns_none(self):
        store = ConversationContextStore()
        assert store.get("missing") is None

    def test_upsert_and_get(self):
        store = ConversationContextStore()
        ctx = ConversationContext(session_id="s1")
        ctx.summary = "Discussed AAPL"
        store.upsert("s1", ctx)
        result = store.get("s1")
        assert result is not None
        assert result.summary == "Discussed AAPL"

    def test_cleanup_evicts_expired(self):
        store = ConversationContextStore(ttl=1)
        ctx = ConversationContext(session_id="s1")
        ctx.last_updated = time.time() - 10
        store.upsert("s1", ctx)
        store.cleanup()
        assert store.get("s1") is None

    def test_cleanup_keeps_fresh(self):
        store = ConversationContextStore(ttl=3600)
        ctx = ConversationContext(session_id="s1")
        ctx.last_updated = time.time()
        store.upsert("s1", ctx)
        store.cleanup()
        assert store.get("s1") is not None

    def test_delete(self):
        store = ConversationContextStore()
        ctx = ConversationContext(session_id="s1")
        store.upsert("s1", ctx)
        store.delete("s1")
        assert store.get("s1") is None
