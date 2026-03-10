"""Three-tier Groq/Anthropic LLM router with budget-aware routing.

Provides :class:`FallbackLLM`, a duck-typed LLM that routes requests
through up to three tiers:

1. **Router model** — high-TPM Groq model for early tool-calling
   iterations (< ``responder_iteration_threshold``).
2. **Responder model** — best Groq model, preferred from iteration
   ``responder_iteration_threshold`` onward (synthesis phase).
3. **Anthropic fallback** — paid provider, used only when both Groq
   models are exhausted or unavailable.

When ``GROQ_API_KEY`` is not set, tiers 1 and 2 are skipped entirely
and all requests go directly to Anthropic.

Typical usage::

    from token_budget import TokenBudget
    from message_compressor import MessageCompressor
    from llm_fallback import FallbackLLM

    budget = TokenBudget()
    compressor = MessageCompressor()
    llm = FallbackLLM(
        router_model="meta-llama/llama-4-scout-17b-16e-instruct",
        responder_model="openai/gpt-oss-120b",
        anthropic_model="claude-sonnet-4-6",
        temperature=0.0,
        agent_id="stock",
        token_budget=budget,
        compressor=compressor,
    )
"""

import logging
import os
from typing import Any, List, Optional

from langchain_anthropic import ChatAnthropic
from message_compressor import MessageCompressor
from token_budget import TokenBudget

_logger = logging.getLogger(__name__)

# Groq imports are optional — only needed when GROQ_API_KEY is set.
try:
    from groq import (
        APIConnectionError,
        APIStatusError,
        RateLimitError,
    )
    from langchain_groq import ChatGroq

    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False


class FallbackLLM:
    """Three-tier LLM router: router -> responder -> anthropic.

    The router/responder split is invisible to the caller — the
    same ``bind_tools`` / ``invoke`` interface is preserved.

    Attributes:
        _router_model: Model name for the high-TPM router.
        _responder_model: Model name for the best-quality responder.
        _router_llm: Raw ChatGroq for router, or ``None``.
        _responder_llm: Raw ChatGroq for responder, or ``None``.
        _anthropic_llm: Raw ChatAnthropic instance.
        _budget: Shared :class:`TokenBudget` tracker.
        _compressor: Shared :class:`MessageCompressor`.
        _agent_id: Agent identifier for log messages.
    """

    def __init__(
        self,
        router_model: str,
        responder_model: str,
        anthropic_model: str,
        temperature: float,
        agent_id: str,
        token_budget: TokenBudget,
        compressor: MessageCompressor,
        responder_iteration_threshold: int = 4,
    ) -> None:
        """Construct all three inner LLMs.

        Groq is only instantiated when ``GROQ_API_KEY`` is present
        in the environment.  Otherwise, all calls go directly to
        Anthropic.

        Args:
            router_model: High-TPM Groq model for tool routing.
            responder_model: Best Groq model for synthesis.
            anthropic_model: Anthropic model name.
            temperature: Sampling temperature for all LLMs.
            agent_id: Agent identifier for logs.
            token_budget: Shared sliding-window budget tracker.
            compressor: Shared message compressor.
            responder_iteration_threshold: Iterations at or above
                this value prefer the responder model first.
        """
        self._router_model = router_model
        self._responder_model = responder_model
        self._agent_id = agent_id
        self._budget = token_budget
        self._compressor = compressor
        self._resp_iter_threshold = responder_iteration_threshold

        # Groq LLMs (optional).
        self._router_llm: Optional[Any] = None
        self._responder_llm: Optional[Any] = None
        self._router_bound: Optional[Any] = None
        self._responder_bound: Optional[Any] = None

        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if _GROQ_AVAILABLE and groq_key:
            self._router_llm = ChatGroq(
                model=router_model,
                temperature=temperature,
                max_retries=0,
            )
            self._router_bound = self._router_llm

            # Only create a separate responder if it differs
            # from the router model.
            if responder_model != router_model:
                self._responder_llm = ChatGroq(
                    model=responder_model,
                    temperature=temperature,
                    max_retries=0,
                )
                self._responder_bound = self._responder_llm
            else:
                self._responder_llm = self._router_llm
                self._responder_bound = self._router_bound

            _logger.info(
                "FallbackLLM: Groq enabled — "
                "router=%s, responder=%s (agent=%s)",
                router_model,
                responder_model,
                agent_id,
            )
        else:
            _logger.info(
                "FallbackLLM: Groq unavailable "
                "(no GROQ_API_KEY) — Anthropic only "
                "(agent=%s)",
                agent_id,
            )

        # Anthropic is always available.
        self._anthropic_llm = ChatAnthropic(
            model=anthropic_model,
            temperature=temperature,
        )
        self._anthropic_bound: Any = self._anthropic_llm

    def bind_tools(self, tools: List[Any], **kwargs: Any) -> "FallbackLLM":
        """Bind tools to all inner LLMs and return *self*.

        Args:
            tools: LangChain tool objects to bind.
            **kwargs: Extra keyword arguments forwarded to
                each inner ``bind_tools`` call.

        Returns:
            This :class:`FallbackLLM` instance.
        """
        if self._router_llm is not None:
            self._router_bound = self._router_llm.bind_tools(tools, **kwargs)
        if (
            self._responder_llm is not None
            and self._responder_llm is not self._router_llm
        ):
            self._responder_bound = self._responder_llm.bind_tools(
                tools, **kwargs
            )
        elif self._responder_llm is self._router_llm:
            self._responder_bound = self._router_bound

        self._anthropic_bound = self._anthropic_llm.bind_tools(tools, **kwargs)
        return self

    def invoke(
        self,
        messages: List[Any],
        *,
        iteration: int = 1,
        **kwargs: Any,
    ) -> Any:
        """Route to the best available model with compression.

        Decision flow:

        1. Compress messages (default 3 stages).
        2. Estimate tokens.
        3. Build priority list (iteration-aware ordering).
        4. For each tier: if default compression exceeds budget,
           apply progressive compression targeting that model's
           TPM.  Then invoke if affordable.
        5. On budget exhaustion or ``RateLimitError``, cascade.
        6. Anthropic as final fallback.

        Args:
            messages: Ordered list of LangChain BaseMessage objects.
            iteration: Current agentic loop iteration (1-based).
            **kwargs: Extra keyword arguments forwarded to the
                inner ``invoke`` call.

        Returns:
            An AIMessage from whichever provider responded.

        Raises:
            Exception: Re-raised if all providers fail.
        """
        # Step 1: Compress messages (default 3 stages).
        compressed = self._compressor.compress(
            messages,
            iteration,
        )

        # Step 2: Estimate tokens.
        est = self._budget.estimate_tokens(compressed)

        # Step 3: Build priority list of Groq models.
        groq_tiers = self._build_priority(est, iteration)

        # Step 4: Try each Groq tier.
        for model_name, bound_llm in groq_tiers:
            cur_compressed = compressed
            cur_est = est

            # If this model can't afford the default
            # compression, try progressive compression
            # targeting its TPM.
            if not self._budget.can_afford(model_name, cur_est):
                tpm = self._budget.get_tpm(model_name)
                if tpm is not None:
                    # Target 70% of TPM to leave headroom
                    # for estimation inaccuracy.
                    target = int(tpm * 0.70)
                    cur_compressed = self._compressor.compress(
                        messages,
                        iteration,
                        target_tokens=target,
                    )
                    cur_est = self._budget.estimate_tokens(cur_compressed)
                    _logger.info(
                        "Progressive compress for %s: "
                        "%d → %d tokens (agent=%s)",
                        model_name,
                        est,
                        cur_est,
                        self._agent_id,
                    )

            if not self._budget.can_afford(model_name, cur_est):
                _logger.info(
                    "Skip %s: budget exhausted " "(est=%d, agent=%s)",
                    model_name,
                    cur_est,
                    self._agent_id,
                )
                continue

            try:
                result = bound_llm.invoke(cur_compressed, **kwargs)
                self._budget.record(model_name, cur_est)
                _logger.info(
                    "Route → %s | iter=%d " "tokens≈%d (agent=%s)",
                    model_name,
                    iteration,
                    cur_est,
                    self._agent_id,
                )
                return result
            except Exception as exc:
                if _GROQ_AVAILABLE and isinstance(
                    exc,
                    (
                        RateLimitError,
                        APIConnectionError,
                        APIStatusError,
                    ),
                ):
                    _logger.warning(
                        "Groq %s failed (%s), " "cascading — agent=%s",
                        model_name,
                        exc,
                        self._agent_id,
                    )
                    continue
                raise

        # Step 5: Anthropic fallback.
        _logger.warning(
            "All Groq models exhausted → Anthropic | "
            "iter=%d tokens≈%d (agent=%s)",
            iteration,
            est,
            self._agent_id,
        )
        return self._anthropic_bound.invoke(compressed, **kwargs)

    def _build_priority(self, _est: int, iteration: int = 1) -> List[tuple]:
        """Build ordered list of ``(model_name, bound_llm)`` tuples.

        Early iterations (< threshold) prefer the router (small,
        high-TPM) model for tool-calling.  Later iterations
        (>= threshold) prefer the responder (large, better-quality)
        model for synthesis.

        If router and responder are the same model, return only
        one entry to avoid double attempts.

        Args:
            est: Estimated token count (reserved for future use).
            iteration: Current agentic loop iteration (1-based).

        Returns:
            List of ``(model_name, bound_llm)`` pairs.
        """
        same_model = self._responder_model == self._router_model

        # Same model — single entry, no ordering decision.
        if same_model:
            if self._router_bound is not None:
                return [(self._router_model, self._router_bound)]
            return []

        router_entry = (
            (self._router_model, self._router_bound)
            if self._router_bound is not None
            else None
        )
        responder_entry = (
            (self._responder_model, self._responder_bound)
            if self._responder_bound is not None
            else None
        )

        # Late iterations → responder (large) first.
        prefer_responder = iteration >= self._resp_iter_threshold

        tiers: List[tuple] = []
        if prefer_responder:
            if responder_entry:
                tiers.append(responder_entry)
            if router_entry:
                tiers.append(router_entry)
        else:
            if router_entry:
                tiers.append(router_entry)
            if responder_entry:
                tiers.append(responder_entry)

        if prefer_responder and tiers:
            _logger.info(
                "Iteration %d >= %d → responder-first " "(agent=%s)",
                iteration,
                self._resp_iter_threshold,
                self._agent_id,
            )
        return tiers
