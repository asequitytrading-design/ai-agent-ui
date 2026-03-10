"""General-purpose agent with three-tier Groq/Anthropic LLM routing.

:class:`GeneralAgent` is the default agent registered at server startup.
It extends :class:`~agents.base.BaseAgent` and is wired with two tools:
:func:`~tools.time_tool.get_current_time` and
:func:`~tools.search_tool.search_web`.

The agent uses :class:`~llm_fallback.FallbackLLM` which routes through
a high-TPM router model, a quality responder model, and falls back to
Anthropic Claude only when both Groq models are exhausted.

Typical usage::

    from tools.registry import ToolRegistry
    from agents.general_agent import create_general_agent

    registry = ToolRegistry()
    # (register tools first)
    agent = create_general_agent(registry)
    reply = agent.run("What is the current time?")
"""

from agents.base import AgentConfig, BaseAgent
from config import get_settings
from llm_fallback import FallbackLLM
from message_compressor import MessageCompressor
from token_budget import TokenBudget
from tools.registry import ToolRegistry


class GeneralAgent(BaseAgent):
    """General-purpose agent with three-tier LLM routing.

    Inherits the agentic loop from :class:`~agents.base.BaseAgent`
    and overrides :meth:`_build_llm` to supply FallbackLLM with
    budget-aware routing.
    """

    def _build_llm(self) -> FallbackLLM:
        """Instantiate a three-tier :class:`~llm_fallback.FallbackLLM`.

        Uses the shared :attr:`token_budget` and :attr:`compressor`
        from the agent instance (injected by the factory function).

        Returns:
            A :class:`~llm_fallback.FallbackLLM` with router,
            responder, and Anthropic tiers.
        """
        return FallbackLLM(
            router_model=(self.config.router_model or self.config.model),
            responder_model=self.config.model,
            anthropic_model="claude-sonnet-4-6",
            temperature=self.config.temperature,
            agent_id=self.config.agent_id,
            token_budget=self.token_budget,
            compressor=self.compressor,
            responder_iteration_threshold=(
                self.config.responder_iteration_threshold
            ),
        )


def create_general_agent(
    tool_registry: ToolRegistry,
    token_budget: TokenBudget | None = None,
    compressor: MessageCompressor | None = None,
) -> GeneralAgent:
    """Build a :class:`GeneralAgent` with default settings.

    Args:
        tool_registry: The shared :class:`~tools.registry.ToolRegistry`.
        token_budget: Shared :class:`TokenBudget` instance.
            Created with defaults if ``None``.
        compressor: Shared :class:`MessageCompressor` instance.
            Created with defaults if ``None``.

    Returns:
        A ready-to-use :class:`GeneralAgent` instance.
    """
    settings = get_settings()
    config = AgentConfig(
        agent_id="general",
        name="General Agent",
        description=(
            "A general-purpose agent that can answer"
            " questions and search the web."
        ),
        model=settings.groq_responder_model,
        router_model=settings.groq_router_model,
        temperature=0.0,
        tool_names=["get_current_time", "search_web"],
        responder_iteration_threshold=(settings.responder_iteration_threshold),
    )
    agent = GeneralAgent(config=config, tool_registry=tool_registry)
    agent.token_budget = token_budget or TokenBudget()
    agent.compressor = compressor or MessageCompressor(
        max_history_turns=settings.max_history_turns,
        max_tool_result_chars=settings.max_tool_result_chars,
    )
    return agent
