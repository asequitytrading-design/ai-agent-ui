"""Unit tests for the three-tier FallbackLLM router.

Tests cover:
- Primary (Groq router) path succeeds → Anthropic is never called.
- Groq raises RateLimitError → falls back to Anthropic.
- Groq raises APIConnectionError → falls back to Anthropic.
- Both fail → re-raises the Anthropic error.
- bind_tools() stores bound LLMs and returns ``self``.
- Iteration-aware routing: router-first early, responder-first late.
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


# ---------------------------------------------------------------------------
# Helper for two-model (router ≠ responder) tests
# ---------------------------------------------------------------------------


def _make_two_model_fallback(
    router_mock,
    responder_mock,
    anthropic_mock,
    threshold=4,
):
    """Build FallbackLLM with distinct router and responder mocks.

    Unlike :func:`_make_fallback`, this uses different model names
    so the code creates separate LLM instances for each tier.
    """
    import llm_fallback

    budget_mock = MagicMock()
    budget_mock.estimate_tokens.return_value = 100
    budget_mock.can_afford.return_value = True

    compressor_mock = MagicMock()
    compressor_mock.compress.side_effect = lambda msgs, *a, **kw: msgs

    # ChatGroq is called twice — first for router, then responder.
    groq_instances = iter([router_mock, responder_mock])

    with (
        patch.object(
            llm_fallback,
            "ChatGroq",
            side_effect=lambda **kw: next(groq_instances),
        ),
        patch.object(
            llm_fallback,
            "ChatAnthropic",
            return_value=anthropic_mock,
        ),
        patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}),
    ):
        llm = llm_fallback.FallbackLLM(
            router_model="model-small",
            responder_model="model-large",
            anthropic_model="claude-sonnet-4-6",
            temperature=0.0,
            agent_id="test",
            token_budget=budget_mock,
            compressor=compressor_mock,
            responder_iteration_threshold=threshold,
        )
    return llm


# ---------------------------------------------------------------------------
# Iteration-aware routing tests
# ---------------------------------------------------------------------------


class TestIterationAwareRouting:
    """Verify router-first for early iterations, responder-first later."""

    def test_early_iteration_uses_router(self):
        """Iterations below threshold prefer the router model."""
        router_mock = MagicMock()
        responder_mock = MagicMock()
        anthropic_mock = MagicMock()
        router_mock.invoke.return_value = "router_response"
        responder_mock.invoke.return_value = "responder_response"

        llm = _make_two_model_fallback(
            router_mock,
            responder_mock,
            anthropic_mock,
            threshold=4,
        )

        result = llm.invoke("hello", iteration=1)

        assert result == "router_response"
        router_mock.invoke.assert_called_once()
        responder_mock.invoke.assert_not_called()

    def test_late_iteration_uses_responder(self):
        """Iterations at or above threshold prefer responder."""
        router_mock = MagicMock()
        responder_mock = MagicMock()
        anthropic_mock = MagicMock()
        router_mock.invoke.return_value = "router_response"
        responder_mock.invoke.return_value = "responder_response"

        llm = _make_two_model_fallback(
            router_mock,
            responder_mock,
            anthropic_mock,
            threshold=4,
        )

        result = llm.invoke("hello", iteration=4)

        assert result == "responder_response"
        responder_mock.invoke.assert_called_once()
        router_mock.invoke.assert_not_called()

    def test_late_iteration_falls_back_to_router(self):
        """If responder budget exhausted, falls back to router."""
        router_mock = MagicMock()
        responder_mock = MagicMock()
        anthropic_mock = MagicMock()
        router_mock.invoke.return_value = "router_fallback"

        llm = _make_two_model_fallback(
            router_mock,
            responder_mock,
            anthropic_mock,
            threshold=4,
        )
        # Make responder unaffordable.
        llm._budget.can_afford.side_effect = (
            lambda model, est: model != "model-large"
        )

        result = llm.invoke("hello", iteration=5)

        assert result == "router_fallback"
        router_mock.invoke.assert_called_once()
        responder_mock.invoke.assert_not_called()

    def test_threshold_boundary_uses_responder(self):
        """Iteration exactly at threshold uses responder."""
        router_mock = MagicMock()
        responder_mock = MagicMock()
        anthropic_mock = MagicMock()
        responder_mock.invoke.return_value = "resp"

        llm = _make_two_model_fallback(
            router_mock,
            responder_mock,
            anthropic_mock,
            threshold=3,
        )

        result = llm.invoke("hello", iteration=3)

        assert result == "resp"
        responder_mock.invoke.assert_called_once()
        router_mock.invoke.assert_not_called()

    def test_progressive_compression_fits_responder(self):
        """Progressive compression shrinks messages to fit responder."""
        router_mock = MagicMock()
        responder_mock = MagicMock()
        anthropic_mock = MagicMock()
        responder_mock.invoke.return_value = "synthesised"

        llm = _make_two_model_fallback(
            router_mock,
            responder_mock,
            anthropic_mock,
            threshold=4,
        )

        # First can_afford → False (default compression too big).
        # After progressive compress, estimate drops → True.
        call_count = {"n": 0}

        def _can_afford(model, est):
            call_count["n"] += 1
            if model == "model-large":
                # First check fails, second (after
                # progressive compress) succeeds.
                return call_count["n"] > 1
            return True

        llm._budget.can_afford.side_effect = _can_afford
        llm._budget.get_tpm.return_value = 8000

        result = llm.invoke("hello", iteration=5)

        assert result == "synthesised"
        responder_mock.invoke.assert_called_once()
        router_mock.invoke.assert_not_called()
        # Compressor called twice: default + progressive.
        assert llm._compressor.compress.call_count == 2
        # Second call includes target_tokens.
        second_call = llm._compressor.compress.call_args_list[1]
        # 70% of 8000 TPM = 5600 headroom target.
        assert second_call.kwargs.get("target_tokens") == 5600

    def test_progressive_compression_still_too_big(self):
        """If progressive compression isn't enough, cascade."""
        router_mock = MagicMock()
        responder_mock = MagicMock()
        anthropic_mock = MagicMock()
        router_mock.invoke.return_value = "router_fallback"

        llm = _make_two_model_fallback(
            router_mock,
            responder_mock,
            anthropic_mock,
            threshold=4,
        )

        # Responder always unaffordable (even after compress).
        llm._budget.can_afford.side_effect = (
            lambda model, est: model != "model-large"
        )
        llm._budget.get_tpm.return_value = 8000

        result = llm.invoke("hello", iteration=5)

        assert result == "router_fallback"
        router_mock.invoke.assert_called_once()
        responder_mock.invoke.assert_not_called()
