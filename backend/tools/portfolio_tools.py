"""Portfolio analysis tools for the Portfolio Agent.

All tools read exclusively from Iceberg + Redis —
zero external API calls.  They compute portfolio
metrics from local data: holdings, OHLCV prices,
company info, dividends, and forecasts.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from langchain_core.tools import tool

from tools._stock_shared import _require_repo
from tools._ticker_linker import get_current_user

_logger = logging.getLogger(__name__)


def _get_user_or_error() -> str:
    """Get current user_id or raise."""
    uid = get_current_user()
    if not uid:
        raise RuntimeError(
            "No user context — cannot access "
            "portfolio data.",
        )
    return uid


def _current_price(
    repo, ticker: str,
) -> float | None:
    """Get latest close price from Iceberg OHLCV."""
    ohlcv = repo.get_ohlcv(ticker)
    if ohlcv.empty:
        return None
    return float(ohlcv.iloc[-1]["close"])


# ---------------------------------------------------------------
# Tool 1: get_portfolio_holdings
# ---------------------------------------------------------------


@tool
def get_portfolio_holdings() -> str:
    """Get user's portfolio holdings with values.

    Returns ticker, quantity, avg_price, current_price,
    market_value, unrealized_pnl, and weight_pct for
    each holding.

    Source: Iceberg portfolio_transactions + ohlcv.
    """
    user_id = _get_user_or_error()
    repo = _require_repo()
    holdings = repo.get_portfolio_holdings(user_id)

    if holdings.empty:
        return (
            "No portfolio holdings found. "
            "Add stocks via the Portfolio page."
        )

    rows = []
    total_value = 0.0
    for _, h in holdings.iterrows():
        ticker = h["ticker"]
        qty = float(h["quantity"])
        avg = float(h["avg_price"])
        curr = _current_price(repo, ticker)
        invested = qty * avg
        mkt_val = qty * curr if curr else invested
        pnl = mkt_val - invested
        pnl_pct = (
            (pnl / invested * 100) if invested else 0
        )
        total_value += mkt_val
        rows.append({
            "ticker": ticker,
            "qty": qty,
            "avg": round(avg, 2),
            "curr": round(curr, 2) if curr else None,
            "invested": round(invested, 2),
            "value": round(mkt_val, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "currency": h.get("currency", "INR"),
        })

    # Compute weights
    for r in rows:
        r["weight"] = round(
            r["value"] / total_value * 100, 1,
        ) if total_value else 0

    lines = [
        "[Source: iceberg]",
        f"**Portfolio Holdings** "
        f"(as of {date.today()})\n",
        "| Ticker | Qty | Avg | Current | "
        "Value | P&L | P&L% | Weight |",
        "|--------|-----|-----|---------|"
        "-------|-----|------|--------|",
    ]
    for r in rows:
        curr_str = (
            f"{r['curr']}" if r['curr'] else "N/A"
        )
        lines.append(
            f"| {r['ticker']} | {r['qty']} | "
            f"{r['avg']} | {curr_str} | "
            f"{r['value']} | {r['pnl']} | "
            f"{r['pnl_pct']}% | {r['weight']}% |"
        )

    total_invested = sum(r["invested"] for r in rows)
    total_pnl = total_value - total_invested
    lines.append(
        f"\n**Total**: Value={round(total_value, 2)} "
        f"| Invested={round(total_invested, 2)} "
        f"| P&L={round(total_pnl, 2)}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------
# Tool 2: get_portfolio_performance
# ---------------------------------------------------------------


@tool
def get_portfolio_performance(
    period: str = "6M",
) -> str:
    """Get portfolio performance over a period.

    Returns total_return, annualized_return, best_day,
    worst_day, max_drawdown.

    Args:
        period: One of 1M, 3M, 6M, 1Y, ALL.

    Source: Iceberg ohlcv + portfolio_transactions.
    """
    user_id = _get_user_or_error()
    repo = _require_repo()
    holdings = repo.get_portfolio_holdings(user_id)

    if holdings.empty:
        return "No portfolio holdings found."

    # Determine date range
    period_days = {
        "1M": 30, "3M": 90, "6M": 180,
        "1Y": 365, "ALL": 3650,
    }
    days = period_days.get(
        period.upper(), 180,
    )
    start = date.today() - pd.Timedelta(days=days)

    # Build daily portfolio value series
    all_prices = {}
    for _, h in holdings.iterrows():
        ticker = h["ticker"]
        qty = float(h["quantity"])
        ohlcv = repo.get_ohlcv(ticker, start=start)
        if ohlcv.empty:
            continue
        ohlcv = ohlcv.set_index("date")
        all_prices[ticker] = (
            ohlcv["close"].astype(float) * qty
        )

    if not all_prices:
        return "No price data available for holdings."

    portfolio = pd.DataFrame(all_prices)
    portfolio = portfolio.ffill().dropna(how="all")
    daily_value = portfolio.sum(axis=1)

    if len(daily_value) < 2:
        return "Insufficient data for performance."

    # Compute metrics
    total_return = (
        (daily_value.iloc[-1] / daily_value.iloc[0])
        - 1
    ) * 100
    daily_returns = daily_value.pct_change().dropna()
    ann_return = (
        daily_returns.mean() * 252 * 100
    )
    ann_vol = daily_returns.std() * np.sqrt(252) * 100
    best_day = daily_returns.max() * 100
    worst_day = daily_returns.min() * 100

    # Max drawdown
    peak = daily_value.cummax()
    drawdown = (daily_value - peak) / peak
    max_dd = drawdown.min() * 100

    # Sharpe (risk-free = 5%)
    rf_daily = 0.05 / 252
    sharpe = (
        (daily_returns.mean() - rf_daily)
        / daily_returns.std()
        * np.sqrt(252)
    ) if daily_returns.std() > 0 else 0

    return (
        f"[Source: iceberg]\n"
        f"**Portfolio Performance ({period})**\n"
        f"Period: {daily_value.index[0]} to "
        f"{daily_value.index[-1]}\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Total Return | {total_return:.2f}% |\n"
        f"| Annualized Return | {ann_return:.2f}% |\n"
        f"| Annualized Vol | {ann_vol:.2f}% |\n"
        f"| Sharpe Ratio | {sharpe:.2f} |\n"
        f"| Max Drawdown | {max_dd:.2f}% |\n"
        f"| Best Day | +{best_day:.2f}% |\n"
        f"| Worst Day | {worst_day:.2f}% |"
    )


# ---------------------------------------------------------------
# Tool 3: get_sector_allocation
# ---------------------------------------------------------------


@tool
def get_sector_allocation() -> str:
    """Get portfolio sector breakdown by market value.

    Returns sector, weight_pct, market_value,
    ticker_count.

    Source: Iceberg portfolio_transactions + company_info.
    """
    user_id = _get_user_or_error()
    repo = _require_repo()
    holdings = repo.get_portfolio_holdings(user_id)

    if holdings.empty:
        return "No portfolio holdings found."

    sectors: dict[str, dict] = {}
    total_value = 0.0

    for _, h in holdings.iterrows():
        ticker = h["ticker"]
        qty = float(h["quantity"])
        curr = _current_price(repo, ticker)
        mkt_val = qty * (curr or float(h["avg_price"]))
        total_value += mkt_val

        info = repo.get_latest_company_info(ticker)
        sector = (
            info.get("sector", "Unknown")
            if info else "Unknown"
        )

        if sector not in sectors:
            sectors[sector] = {
                "value": 0, "tickers": [],
            }
        sectors[sector]["value"] += mkt_val
        sectors[sector]["tickers"].append(ticker)

    if not sectors:
        return "No sector data available."

    lines = [
        "[Source: iceberg]",
        f"**Sector Allocation** "
        f"(as of {date.today()})\n",
        "| Sector | Weight | Value | Tickers |",
        "|--------|--------|-------|---------|",
    ]
    for sector in sorted(
        sectors,
        key=lambda s: sectors[s]["value"],
        reverse=True,
    ):
        s = sectors[sector]
        weight = (
            s["value"] / total_value * 100
            if total_value else 0
        )
        tickers_str = ", ".join(s["tickers"])
        lines.append(
            f"| {sector} | {weight:.1f}% | "
            f"{s['value']:.2f} | {tickers_str} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------
# Tool 4: get_dividend_projection
# ---------------------------------------------------------------


@tool
def get_dividend_projection() -> str:
    """Project annual dividend income from holdings.

    Returns per-ticker annual dividend, yield, and
    total projected income.

    Source: Iceberg dividends + portfolio_transactions.
    """
    user_id = _get_user_or_error()
    repo = _require_repo()
    holdings = repo.get_portfolio_holdings(user_id)

    if holdings.empty:
        return "No portfolio holdings found."

    lines = [
        "[Source: iceberg]",
        "**Dividend Income Projection**\n",
        "| Ticker | Qty | Ann Div/Share | "
        "Annual Income | Yield |",
        "|--------|-----|--------------|"
        "--------------|-------|",
    ]
    total_income = 0.0

    for _, h in holdings.iterrows():
        ticker = h["ticker"]
        qty = float(h["quantity"])
        curr = _current_price(repo, ticker)

        divs = repo.get_dividends(ticker)
        if divs.empty:
            continue

        # Annualize from last 4 payments
        recent = divs.tail(4)
        ann_div = float(
            recent["dividend_amount"].sum()
        )
        income = ann_div * qty
        total_income += income

        yld = (
            (ann_div / curr * 100)
            if curr and curr > 0 else 0
        )

        lines.append(
            f"| {ticker} | {qty} | "
            f"{ann_div:.2f} | {income:.2f} | "
            f"{yld:.2f}% |"
        )

    lines.append(
        f"\n**Total Projected Annual Income**: "
        f"{total_income:.2f}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------
# Tool 5: suggest_rebalancing
# ---------------------------------------------------------------


@tool
def suggest_rebalancing() -> str:
    """Suggest portfolio rebalancing actions.

    Identifies over-concentrated positions and
    suggests adjustments.

    Source: Iceberg (all local computation).
    """
    user_id = _get_user_or_error()
    repo = _require_repo()
    holdings = repo.get_portfolio_holdings(user_id)

    if holdings.empty:
        return "No portfolio holdings found."

    # Build holdings with values and sectors
    rows = []
    total_value = 0.0
    for _, h in holdings.iterrows():
        ticker = h["ticker"]
        qty = float(h["quantity"])
        curr = _current_price(repo, ticker)
        val = qty * (curr or float(h["avg_price"]))
        total_value += val

        info = repo.get_latest_company_info(ticker)
        sector = (
            info.get("sector", "Unknown")
            if info else "Unknown"
        )
        market = h.get("market", "india")
        rows.append({
            "ticker": ticker,
            "value": val,
            "sector": sector,
            "market": market,
        })

    if not total_value:
        return "Cannot compute — zero portfolio value."

    suggestions = []

    # 1. Sector concentration (>30%)
    sector_weights: dict[str, float] = {}
    for r in rows:
        s = r["sector"]
        sector_weights[s] = (
            sector_weights.get(s, 0)
            + r["value"] / total_value * 100
        )
    for s, w in sector_weights.items():
        if w > 30:
            suggestions.append(
                f"**{s}** sector is {w:.1f}% "
                f"(>30%) — consider reducing to 25%"
            )

    # 2. Single-stock concentration (>20%)
    for r in rows:
        w = r["value"] / total_value * 100
        if w > 20:
            suggestions.append(
                f"**{r['ticker']}** is {w:.1f}% "
                f"(>20%) — consider capping at 15%"
            )

    # 3. Market concentration (>80%)
    india_pct = sum(
        r["value"] for r in rows
        if r["market"] == "india"
    ) / total_value * 100
    us_pct = 100 - india_pct
    if india_pct > 80:
        suggestions.append(
            f"India market is {india_pct:.0f}% — "
            "consider adding US stocks for "
            "geographic diversification"
        )
    elif us_pct > 80:
        suggestions.append(
            f"US market is {us_pct:.0f}% — "
            "consider adding India stocks for "
            "geographic diversification"
        )

    if not suggestions:
        return (
            "[Source: iceberg]\n"
            "**Portfolio Rebalancing**\n\n"
            "Your portfolio looks well-diversified. "
            "No concentration risks detected."
        )

    lines = [
        "[Source: iceberg]",
        "**Rebalancing Suggestions**\n",
    ]
    for i, s in enumerate(suggestions, 1):
        lines.append(f"{i}. {s}")

    return "\n".join(lines)


# ---------------------------------------------------------------
# Tool 6: get_portfolio_summary
# ---------------------------------------------------------------


@tool
def get_portfolio_summary() -> str:
    """Quick portfolio overview.

    Returns total invested, current value, P&L,
    top gainer, top loser.

    Source: Iceberg + Redis cache.
    """
    user_id = _get_user_or_error()
    repo = _require_repo()
    holdings = repo.get_portfolio_holdings(user_id)

    if holdings.empty:
        return "No portfolio holdings found."

    rows = []
    for _, h in holdings.iterrows():
        ticker = h["ticker"]
        qty = float(h["quantity"])
        avg = float(h["avg_price"])
        curr = _current_price(repo, ticker)
        invested = qty * avg
        value = qty * (curr or avg)
        pnl_pct = (
            ((value - invested) / invested * 100)
            if invested else 0
        )
        rows.append({
            "ticker": ticker,
            "invested": invested,
            "value": value,
            "pnl_pct": pnl_pct,
        })

    total_invested = sum(r["invested"] for r in rows)
    total_value = sum(r["value"] for r in rows)
    total_pnl = total_value - total_invested
    total_pnl_pct = (
        (total_pnl / total_invested * 100)
        if total_invested else 0
    )

    top_gainer = max(rows, key=lambda r: r["pnl_pct"])
    top_loser = min(rows, key=lambda r: r["pnl_pct"])

    return (
        f"[Source: iceberg]\n"
        f"**Portfolio Summary** "
        f"(as of {date.today()})\n\n"
        f"- **Holdings**: {len(rows)} stocks\n"
        f"- **Total Invested**: "
        f"{total_invested:.2f}\n"
        f"- **Current Value**: "
        f"{total_value:.2f}\n"
        f"- **P&L**: {total_pnl:.2f} "
        f"({total_pnl_pct:+.2f}%)\n"
        f"- **Top Gainer**: "
        f"{top_gainer['ticker']} "
        f"({top_gainer['pnl_pct']:+.1f}%)\n"
        f"- **Top Loser**: "
        f"{top_loser['ticker']} "
        f"({top_loser['pnl_pct']:+.1f}%)"
    )
