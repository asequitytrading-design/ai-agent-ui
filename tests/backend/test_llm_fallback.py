"""Unit tests for the three-tier FallbackLLM router.

Tests cover:
- Primary (Groq router) path succeeds → Anthropic is never called.
- Groq raises RateLimitError → falls back to Anthropic.
- Groq raises APIConnectionError → falls back to Anthropic.
- Both fail → re-raises the Anthropic error.
- bind_tools() stores bound LLMs and returns ``self``.
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fallback(groq_mock, anthropic_mock):
    """Construct a FallbackLLM with inner LLMs already patched.

    Patches ``llm_fallback.ChatGroq`` and ``llm_fallback.ChatAnthropic``
    so that no real API keys are needed.  Also patches the
    ``MessageCompressor`` and ``TokenBudget`` dependencies.

    Uses the same model for router and responder so only one Groq
    mock is needed (the code detects same-model and reuses).
    """
    import llm_fallback

    # TokenBudget mock that always allows everything.
    budget_mock = MagicMock()
    budget_mock.estimate_tokens.return_value = 100
    budget_mock.can_afford.return_value = True

    # Compressor mock that passes messages through.
    compressor_mock = MagicMock()
    compressor_mock.compress.side_effect = lambda msgs, *a, **kw: msgs

    with (
        patch.object(
            llm_fallback,
            "ChatGroq",
            return_value=groq_mock,
        ),
        patch.object(
            llm_fallback,
            "ChatAnthropic",
            return_value=anthropic_mock,
        ),
        patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}),
    ):
        llm = llm_fallback.FallbackLLM(
            router_model="openai/gpt-oss-120b",
            responder_model="openai/gpt-oss-120b",
            anthropic_model="claude-sonnet-4-6",
            temperature=0.0,
            agent_id="test",
            token_budget=budget_mock,
            compressor=compressor_mock,
        )
    return llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFallbackLLMPrimaryPath:
    """Groq succeeds — Anthropic must not be invoked."""

    def test_groq_invoked_and_returns_response(self):
        """When Groq succeeds, the Groq response is returned."""
        groq_mock = MagicMock()
        anthropic_mock = MagicMock()
        groq_mock.bind_tools.return_value = groq_mock
        anthropic_mock.bind_tools.return_value = anthropic_mock
        groq_mock.invoke.return_value = "groq_response"
        anthropic_mock.invoke.return_value = "anthropic_response"

        llm = _make_fallback(groq_mock, anthropic_mock)
        llm.bind_tools([])

        result = llm.invoke("hello")

        assert result == "groq_response"
        groq_mock.invoke.assert_called_once()
        anthropic_mock.invoke.assert_not_called()


class TestFallbackLLMRateLimitFallback:
    """Groq raises RateLimitError → fallback to Anthropic."""

    def test_rate_limit_triggers_anthropic(self):
        """RateLimitError from Groq causes Anthropic to be used."""
        from groq import RateLimitError

        groq_mock = MagicMock()
        anthropic_mock = MagicMock()
        groq_mock.bind_tools.return_value = groq_mock
        anthropic_mock.bind_tools.return_value = anthropic_mock
        groq_mock.invoke.side_effect = RateLimitError(
            "rate limit",
            response=MagicMock(),
            body={},
        )
        anthropic_mock.invoke.return_value = "anthropic_fallback"

        llm = _make_fallback(groq_mock, anthropic_mock)
        llm.bind_tools([])

        result = llm.invoke("hello")

        assert result == "anthropic_fallback"
        anthropic_mock.invoke.assert_called_once()


class TestFallbackLLMConnectionFallback:
    """Groq raises APIConnectionError → fallback to Anthropic."""

    def test_connection_error_triggers_anthropic(self):
        """APIConnectionError causes Anthropic to be used."""
        from groq import APIConnectionError

        groq_mock = MagicMock()
        anthropic_mock = MagicMock()
        groq_mock.bind_tools.return_value = groq_mock
        anthropic_mock.bind_tools.return_value = anthropic_mock
        groq_mock.invoke.side_effect = APIConnectionError(request=MagicMock())
        anthropic_mock.invoke.return_value = "anthropic_fallback"

        llm = _make_fallback(groq_mock, anthropic_mock)
        llm.bind_tools([])

        result = llm.invoke("hello")

        assert result == "anthropic_fallback"
        anthropic_mock.invoke.assert_called_once()


class TestFallbackLLMBothFail:
    """Both Groq and Anthropic fail → re-raise."""

    def test_reraises_when_both_fail(self):
        """When Groq and Anthropic both raise, Anthropic propagates."""
        from groq import RateLimitError

        groq_mock = MagicMock()
        anthropic_mock = MagicMock()
        groq_mock.bind_tools.return_value = groq_mock
        anthropic_mock.bind_tools.return_value = anthropic_mock
        groq_mock.invoke.side_effect = RateLimitError(
            "rate limit",
            response=MagicMock(),
            body={},
        )
        anthropic_mock.invoke.side_effect = RuntimeError(
            "Anthropic also failed"
        )

        llm = _make_fallback(groq_mock, anthropic_mock)
        llm.bind_tools([])

        with pytest.raises(RuntimeError, match="Anthropic also failed"):
            llm.invoke("hello")


class TestFallbackLLMBindTools:
    """bind_tools() duck-types LangChain's interface."""

    def test_bind_tools_returns_self(self):
        """bind_tools() must return the FallbackLLM instance."""
        groq_mock = MagicMock()
        anthropic_mock = MagicMock()
        groq_mock.bind_tools.return_value = groq_mock
        anthropic_mock.bind_tools.return_value = anthropic_mock

        llm = _make_fallback(groq_mock, anthropic_mock)
        result = llm.bind_tools([MagicMock()])

        assert result is llm

    def test_bind_tools_stores_bound_llms(self):
        """bind_tools() stores bound versions of inner LLMs."""
        groq_bound = MagicMock()
        anthropic_bound = MagicMock()
        groq_mock = MagicMock()
        anthropic_mock = MagicMock()
        groq_mock.bind_tools.return_value = groq_bound
        anthropic_mock.bind_tools.return_value = anthropic_bound

        llm = _make_fallback(groq_mock, anthropic_mock)
        tools = [MagicMock()]
        llm.bind_tools(tools)

        groq_mock.bind_tools.assert_called_once_with(tools)
        anthropic_mock.bind_tools.assert_called_once_with(tools)
        assert llm._router_bound is groq_bound
        assert llm._anthropic_bound is anthropic_bound
