"""Portfolio sub-agent configuration.

Handles portfolio queries: holdings, allocation,
performance, dividends, rebalancing.  All tools read
exclusively from Iceberg — zero external API calls.
"""

from __future__ import annotations

from agents.sub_agents import SubAgentConfig

_PORTFOLIO_SYSTEM_PROMPT = (
    "You are a portfolio analyst on the ASET Platform. "
    "You help users understand their stock portfolio "
    "composition, performance, and risk.\n\n"
    "CAPABILITIES:\n"
    "- Portfolio holdings with current values and P&L\n"
    "- Sector allocation breakdown\n"
    "- Performance metrics (returns, Sharpe, "
    "drawdown)\n"
    "- Dividend income projections\n"
    "- Rebalancing suggestions\n"
    "- Quick portfolio summary\n\n"
    "RULES:\n"
    "- All data comes from the user's local portfolio "
    "— never fabricate numbers.\n"
    "- When showing P&L, always include both absolute "
    "amount and percentage.\n"
    "- When suggesting rebalancing, explain the "
    "reasoning (concentration risk, correlation).\n"
    "- If the user has no holdings, suggest adding "
    "stocks via the Portfolio page.\n"
    "- Use the appropriate tool for each query — "
    "don't try to compute metrics manually.\n"
    "- Present data in clear tables when possible."
)

PORTFOLIO_CONFIG = SubAgentConfig(
    agent_id="portfolio",
    name="Portfolio Agent",
    description=(
        "Analyses user portfolio: holdings, "
        "allocation, performance, dividends, "
        "and rebalancing suggestions."
    ),
    system_prompt=_PORTFOLIO_SYSTEM_PROMPT,
    tool_names=[
        "get_portfolio_holdings",
        "get_portfolio_performance",
        "get_sector_allocation",
        "get_dividend_projection",
        "suggest_rebalancing",
        "get_portfolio_summary",
    ],
)
