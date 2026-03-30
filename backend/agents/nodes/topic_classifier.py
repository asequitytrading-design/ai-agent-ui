"""Follow-up vs new-topic classification.

Uses a 1-shot LLM prompt to decide if the user's
message is a continuation of the current topic or
a brand-new question.
"""

from __future__ import annotations

import logging

from agents.conversation_context import (
    ConversationContext,
)

_logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = (
    "Given the conversation summary and the new "
    "user message, classify as 'follow_up' or "
    "'new_topic'.\n\n"
    "Summary: {summary}\n"
    "Last topic: {topic}\n"
    "New message: {message}\n\n"
    "Answer with ONLY 'follow_up' or 'new_topic'."
)


def classify_followup(
    user_input: str,
    ctx: ConversationContext | None,
) -> str:
    """Classify user message as follow-up or new topic.

    Returns ``"new_topic"`` if no context, first turn,
    or classification fails.
    """
    if ctx is None or ctx.turn_count == 0:
        return "new_topic"

    try:
        return _classify_via_llm(user_input, ctx)
    except Exception:
        _logger.debug(
            "Topic classification failed, "
            "defaulting to new_topic",
            exc_info=True,
        )
        return "new_topic"


def _classify_via_llm(
    user_input: str,
    ctx: ConversationContext,
) -> str:
    """Call LLM to classify follow-up vs new topic."""
    from langchain_core.messages import HumanMessage

    from llm_fallback import FallbackLLM

    prompt = _CLASSIFY_PROMPT.format(
        summary=ctx.summary or "No previous context.",
        topic=ctx.current_topic or "None",
        message=user_input,
    )

    llm = FallbackLLM(max_tiers=2)
    result = llm.invoke([HumanMessage(content=prompt)])
    text = (
        result.content
        if hasattr(result, "content")
        else str(result)
    ).strip().lower()

    if "follow" in text:
        return "follow_up"
    return "new_topic"
