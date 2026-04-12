# LLM-Powered Portfolio Recommendations — Design Spec

**Date:** 2026-04-12
**Ticket:** ASETPLTFRM-298
**Estimate:** 8 SP
**Branch:** feature/sprint6

---

## Problem

The current recommendation engine is a hardcoded rule set with 5 static
thresholds (overweight >20%, sector concentration >35%, missing major
sectors, underperformers <-15%, low diversification <5). It cannot:

- Reason about cross-signal interactions (Piotroski + sentiment + forecast)
- Discover new stocks that would fill portfolio gaps
- Adapt recommendations to market conditions
- Track whether its advice was correct over time

We have rich per-ticker data (748 stocks) across 6 Iceberg tables —
technical indicators, fundamentals (Piotroski 0-9), sentiment (-1 to +1),
Prophet forecasts with accuracy metrics, and quarterly financials — but
none of this feeds into recommendations today.

## Goal

Replace the rule-based recommendation widget with a **Smart Funnel**
pipeline: deterministic pre-filter (DuckDB) → portfolio gap analysis →
LLM reasoning pass. Produce 5-8 actionable, portfolio-aware
recommendations per user per month. Track recommendation performance
at 30/60/90 day checkpoints.

## Scope

### In scope (v1)

1. Three PostgreSQL tables (recommendation_runs, recommendations,
   recommendation_outcomes) with Alembic migration
2. Smart Funnel pipeline (3 stages) as a scheduled job
3. New `recommendation` LangGraph sub-agent (6th agent) with 3 new
   tools + 3 shared portfolio tools
4. Upgraded dashboard Recommendations widget (tier badges, signal
   pills, health score)
5. Recommendation History tab on Analytics > Insights page
6. 5 API endpoints (list, refresh, history, detail, stats)
7. Outcome tracker daily job (30/60/90 day checkpoints)
8. Auto-detection of user actions (buy/sell matches active recs)

### Out of scope (future)

- ML-based scoring layer (to research via /sc:research — plugs into
  Stage 1 composite score as additional signal)
- Push notifications (email/in-app) for new recommendations
- Social features (share recommendations, community picks)
- Paper trading / virtual portfolio simulation
- Multi-portfolio support (when that ships, recommendations scope
  to active portfolio)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Monthly Scheduler Job               │
│              (or manual trigger / chat)               │
├──────────┬──────────────────┬────────────────────────┤
│ Stage 1  │     Stage 2      │       Stage 3          │
│ Pre-     │  Portfolio Gap   │    LLM Reasoning       │
│ Filter   │    Analysis      │       Pass             │
│ (DuckDB) │    (Python)      │  (FallbackLLM)         │
│          │                  │                        │
│ 748 → ~150 candidates      │  ~40 candidates        │
│ Composite score 0-100      │  → 5-8 final recs      │
│ Hard gates + weighted      │  + portfolio health     │
│ signals                    │  + narrative rationale  │
└──────────┴──────────────────┴────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────┐      ┌──────────────────────────┐
│   DuckDB Read   │      │   PostgreSQL Write        │
│ (Iceberg tables)│      │ recommendation_runs       │
│ ohlcv           │      │ recommendations           │
│ analysis_summary│      │ recommendation_outcomes   │
│ piotroski_scores│      └──────────────────────────┘
│ sentiment_scores│               │           │
│ forecast_runs   │               ▼           ▼
│ company_info    │      ┌────────────┐ ┌──────────┐
│ stock_tags (PG) │      │ Dashboard  │ │  Chat    │
└─────────────────┘      │  Widget    │ │  Agent   │
                         └────────────┘ └──────────┘
```

---

## Data Model (PostgreSQL)

All three tables in the `stocks` schema, managed via Alembic.

### Table: `stocks.recommendation_runs`

Stores one row per recommendation generation run.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `run_id` | `UUID` | PK, DEFAULT `gen_random_uuid()` | |
| `user_id` | `UUID` | FK → `auth.users` ON DELETE CASCADE, NOT NULL | |
| `run_date` | `DATE` | NOT NULL | Calendar month this run covers |
| `run_type` | `VARCHAR(20)` | NOT NULL | `scheduled` / `manual` / `chat` |
| `portfolio_snapshot` | `JSONB` | NOT NULL | Holdings, weights, sector allocation, total value at run time |
| `health_score` | `FLOAT` | NOT NULL | 0-100 composite portfolio health |
| `health_label` | `VARCHAR(20)` | NOT NULL | `critical` (<30) / `needs_attention` (<60) / `healthy` (<80) / `excellent` (>=80) |
| `candidates_scanned` | `INTEGER` | NOT NULL | Total tickers in pre-filter |
| `candidates_passed` | `INTEGER` | NOT NULL | Tickers passed to LLM stage |
| `llm_model` | `VARCHAR(50)` | | Model that generated final recs |
| `llm_tokens_used` | `INTEGER` | | Input + output tokens |
| `duration_secs` | `FLOAT` | | Total pipeline runtime |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | |

**Indexes:**
- `ix_rec_runs_user_date` on `(user_id, run_date DESC)` — latest run lookup
- `ix_rec_runs_user_id` on `(user_id)` — FK join performance

**`portfolio_snapshot` JSONB structure:**

```json
{
  "total_value": 1250000.0,
  "currency": "INR",
  "holdings_count": 12,
  "holdings": [
    {"ticker": "TCS.NS", "quantity": 50, "avg_price": 3200.0,
     "current_price": 3450.0, "value": 172500.0, "weight_pct": 13.8,
     "sector": "Technology", "market": "india"}
  ],
  "sector_weights": {"Technology": 38.2, "Financial Services": 5.1},
  "market_weights": {"india": 85.0, "us": 15.0},
  "cap_weights": {"largecap": 72.0, "midcap": 18.0, "smallcap": 10.0},
  "nifty50_overlap_count": 4,
  "nifty50_overlap_tickers": ["TCS.NS", "INFY.NS", "RELIANCE.NS", "HDFCBANK.NS"],
  "correlation_alerts": [{"pair": ["TCS.NS", "INFY.NS"], "corr": 0.91}]
}
```

### Table: `stocks.recommendations`

Stores individual recommendations within a run. Immutable after creation
(status field is the only mutable column).

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | `UUID` | PK, DEFAULT `gen_random_uuid()` | |
| `run_id` | `UUID` | FK → `recommendation_runs` ON DELETE CASCADE, NOT NULL | |
| `tier` | `VARCHAR(20)` | NOT NULL | `portfolio` / `watchlist` / `discovery` |
| `category` | `VARCHAR(25)` | NOT NULL | See category enum below |
| `ticker` | `VARCHAR(20)` | | NULL for portfolio-level-only actions |
| `action` | `VARCHAR(15)` | NOT NULL | `buy` / `sell` / `reduce` / `hold` / `accumulate` / `rotate` / `alert` |
| `severity` | `VARCHAR(10)` | NOT NULL | `high` / `medium` / `low` |
| `rationale` | `TEXT` | NOT NULL | LLM-generated explanation (2-4 sentences) |
| `expected_impact` | `TEXT` | | How this improves portfolio health |
| `data_signals` | `JSONB` | NOT NULL | Raw scores — see structure below |
| `price_at_rec` | `FLOAT` | | Stock price at recommendation time |
| `target_price` | `FLOAT` | | From forecast_runs 3M target |
| `expected_return_pct` | `FLOAT` | | `(target - current) / current * 100` |
| `index_tags` | `VARCHAR[]` | | `{'nifty50', 'largecap'}` from stock_tags |
| `status` | `VARCHAR(15)` | NOT NULL, DEFAULT `active` | `active` / `acted_on` / `ignored` / `expired` |
| `acted_on_date` | `DATE` | | When user acted (set by action hook) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | |

**Indexes:**
- `ix_recs_run_id` on `(run_id)` — join to runs
- `ix_recs_ticker_status` on `(ticker, status)` — action matching
- `ix_recs_status_created` on `(status, created_at)` — outcome tracker scan

**Category enum values (7):**

| Category | Action types | Tier sources |
|----------|-------------|--------------|
| `rebalance` | `reduce`, `accumulate` | `portfolio` |
| `exit_reduce` | `sell`, `reduce` | `portfolio` |
| `hold_accumulate` | `hold`, `accumulate` | `portfolio`, `watchlist` |
| `new_buy` | `buy` | `watchlist`, `discovery` |
| `sector_rotation` | `rotate`, `buy`, `reduce` | all tiers |
| `risk_alert` | `alert`, `reduce` | `portfolio` |
| `index_tracking` | `buy` | `watchlist`, `discovery` |

**`data_signals` JSONB structure:**

```json
{
  "composite_score": 84.2,
  "piotroski": 8,
  "piotroski_norm": 88.9,
  "sharpe": 1.4,
  "sharpe_norm": 72.5,
  "annualized_return_pct": 18.3,
  "momentum_norm": 61.2,
  "sentiment": 0.6,
  "sentiment_norm": 80.0,
  "headline_count": 12,
  "forecast_3m_pct": 12.3,
  "forecast_mape": 8.2,
  "forecast_mae": 45.6,
  "forecast_rmse": 62.1,
  "accuracy_factor": 0.88,
  "adjusted_forecast": 10.8,
  "adjusted_forecast_norm": 68.4,
  "technical_bullish_count": 3,
  "technical_signals": {"sma50": "BUY", "sma200": "BUY", "rsi": "NEUTRAL", "macd": "BUY"},
  "technical_norm": 75.0,
  "sector": "Financial Services",
  "sector_gap_pct": -15.2,
  "index_gap": true,
  "gap_fill_bonus": 12.0,
  "gap_adjusted_score": 96.2
}
```

### Table: `stocks.recommendation_outcomes`

Append-only. One row per checkpoint (30d, 60d, 90d) per recommendation.

| Column | Type | Constraint | Notes |
|--------|------|------------|-------|
| `id` | `UUID` | PK, DEFAULT `gen_random_uuid()` | |
| `recommendation_id` | `UUID` | FK → `recommendations` ON DELETE CASCADE, NOT NULL | |
| `check_date` | `DATE` | NOT NULL | When this measurement was taken |
| `days_elapsed` | `INTEGER` | NOT NULL | 30, 60, or 90 |
| `actual_price` | `FLOAT` | NOT NULL | Stock price at check_date |
| `return_pct` | `FLOAT` | NOT NULL | `(actual - price_at_rec) / price_at_rec * 100` |
| `benchmark_return_pct` | `FLOAT` | NOT NULL | Nifty 50 return over same period |
| `excess_return_pct` | `FLOAT` | NOT NULL | `return_pct - benchmark_return_pct` |
| `outcome_label` | `VARCHAR(15)` | NOT NULL | `correct` / `incorrect` / `neutral` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | |

**Indexes:**
- `ix_rec_outcomes_rec_days` UNIQUE on `(recommendation_id, days_elapsed)` —
  prevents duplicate checkpoints
- `ix_rec_outcomes_rec_id` on `(recommendation_id)` — join performance

**Outcome labeling rules:**

| Action | Correct | Incorrect | Neutral |
|--------|---------|-----------|---------|
| `buy` / `accumulate` | return > +2% | return < -2% | -2% to +2% |
| `sell` / `reduce` | return < -2% (price fell, sell was right) | return > +2% (price rose, sell was wrong) | -2% to +2% |
| `hold` | abs(return) < 10% (stable) | abs(return) > 10% (should have acted) | — |
| `alert` / `rotate` | Directional match to alert reasoning | Opposite direction | — |

---

## Smart Funnel Pipeline

### Stage 1: Deterministic Pre-Filter

**Module:** `backend/jobs/recommendation_engine.py`
**Function:** `stage1_prefilter() -> pd.DataFrame`

Executes a single DuckDB query joining 6 tables. This stage is
**user-independent** — same scores for all users. Cached for 1 hour
(subsequent users in same batch reuse results).

#### Hard Gates

All must pass. Tickers failing any gate are excluded.

| Gate | Source | Threshold | Rationale |
|------|--------|-----------|-----------|
| Piotroski score | `piotroski_scores` | `>= 4` | Eliminate fundamentally weak |
| Average volume | `piotroski_scores.avg_volume` OR `company_info.avg_volume` | `>= 10,000` | Liquidity floor |
| Forecast freshness | `forecast_runs.run_date` | `>= today - 30 days` | Stale forecasts unreliable |
| Sentiment freshness | `sentiment_scores.scored_at` | `>= today - 7 days` | Recent sentiment only |
| OHLCV exists | `ohlcv.close` | `IS NOT NULL` (latest date) | Must have price data |
| Forecast accuracy | `forecast_runs.mape` | `< 80` | Extremely inaccurate forecasts excluded |

#### Composite Score Calculation (0-100)

Each signal normalized to 0-100 range, then weighted.

**Signal 1 — Fundamental Quality (weight: 0.25):**
```
piotroski_norm = (piotroski_score / 9) * 100
```
- Range: 44.4 (score 4, min after gate) to 100 (score 9)

**Signal 2 — Risk-Adjusted Return (weight: 0.20):**
```
sharpe_clamped = clamp(sharpe_ratio, -2.0, 4.0)
sharpe_norm = (sharpe_clamped - (-2.0)) / (4.0 - (-2.0)) * 100
```
- Clamped to [-2, 4] to prevent outlier dominance
- Range: 0 (Sharpe -2) to 100 (Sharpe 4)

**Signal 3 — Momentum (weight: 0.15):**
```
return_clamped = clamp(annualized_return_pct, -50.0, 100.0)
momentum_norm = (return_clamped - (-50.0)) / (100.0 - (-50.0)) * 100
```
- Clamped to [-50%, 100%] annualized return

**Signal 4 — Forecast Upside, Accuracy-Adjusted (weight: 0.20):**
```
accuracy_factor = (
    0.5 * max(0, 1 - mape / 100)
  + 0.3 * max(0, 1 - mae / current_price)
  + 0.2 * max(0, 1 - rmse / current_price)
)
adjusted_forecast = target_3m_pct_change * accuracy_factor
forecast_clamped = clamp(adjusted_forecast, -30.0, 50.0)
forecast_norm = (forecast_clamped - (-30.0)) / (50.0 - (-30.0)) * 100
```
- MAPE 5% → accuracy_factor ~0.95, forecast fully trusted
- MAPE 40% → accuracy_factor ~0.55, forecast heavily discounted
- MAPE 80%+ excluded by hard gate

**Signal 5 — Sentiment (weight: 0.10):**
```
sentiment_norm = (avg_score + 1) / 2 * 100
```
- Maps -1..+1 to 0..100. Neutral (0) maps to 50.

**Signal 6 — Technical Alignment (weight: 0.10):**
```
bullish_signals = sum([
    1 if sma_50_signal == 'BUY' else 0,
    1 if sma_200_signal == 'BUY' else 0,
    1 if rsi_signal in ('BUY', 'OVERSOLD_BUY') else 0,
    1 if 'bull' in macd_signal_text.lower() else 0,
])
technical_norm = (bullish_signals / 4) * 100
```
- 0 = all bearish, 100 = all bullish

**Final composite:**
```
composite_score = (
    0.25 * piotroski_norm
  + 0.20 * sharpe_norm
  + 0.15 * momentum_norm
  + 0.20 * forecast_norm
  + 0.10 * sentiment_norm
  + 0.10 * technical_norm
)
```

#### DuckDB Query Strategy

Single batch query using CTEs to join latest rows from each table:

```sql
WITH latest_piotroski AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY ticker ORDER BY score_date DESC
    ) AS rn FROM piotroski_scores
),
latest_analysis AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY ticker ORDER BY analysis_date DESC
    ) AS rn FROM analysis_summary
),
latest_sentiment AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY ticker ORDER BY score_date DESC
    ) AS rn FROM sentiment_scores
),
latest_forecast AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY ticker ORDER BY run_date DESC
    ) AS rn FROM forecast_runs
    WHERE horizon_months > 0
),
latest_price AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY ticker ORDER BY date DESC
    ) AS rn FROM ohlcv
    WHERE close IS NOT NULL
)
SELECT
    p.ticker,
    p.total_score AS piotroski,
    p.sector, p.industry, p.market_cap, p.avg_volume, p.company_name,
    a.sharpe_ratio, a.annualized_return_pct, a.annualized_volatility_pct,
    a.max_drawdown_pct,
    a.sma_50_signal, a.sma_200_signal, a.rsi_signal, a.macd_signal_text,
    s.avg_score AS sentiment, s.headline_count,
    f.target_3m_pct_change, f.target_3m_price,
    f.mape, f.mae, f.rmse,
    f.target_6m_pct_change, f.target_9m_pct_change,
    pr.close AS current_price, pr.date AS price_date
FROM latest_piotroski p
JOIN latest_analysis a ON a.ticker = p.ticker AND a.rn = 1
JOIN latest_sentiment s ON s.ticker = p.ticker AND s.rn = 1
JOIN latest_forecast f ON f.ticker = p.ticker AND f.rn = 1
JOIN latest_price pr ON pr.ticker = p.ticker AND pr.rn = 1
WHERE p.rn = 1
  AND p.total_score >= 4
  AND COALESCE(p.avg_volume, 0) >= 10000
  AND f.run_date >= CURRENT_DATE - INTERVAL '30 days'
  AND s.score_date >= CURRENT_DATE - INTERVAL '7 days'
  AND COALESCE(f.mape, 999) < 80
```

**Performance note:** This is a full scan of 5 Iceberg tables but each
is small (<5K rows). DuckDB handles this in <2s based on existing
benchmarks (screener: 0.11s for similar join patterns).

#### Output

DataFrame with ~100-200 rows, each containing:
- All raw signal values
- All normalized signal values
- Composite score
- Sector, industry, market cap, company name
- Current price, forecast targets

Cached in-memory for 1 hour (`_PREFILTER_CACHE` with TTL, same pattern
as `_MARKET_CACHE` in `_forecast_shared.py`).

---

### Stage 2: Portfolio Gap Analysis

**Module:** `backend/jobs/recommendation_engine.py`
**Function:** `stage2_gap_analysis(user_id, candidates_df) -> dict`

Per-user analysis. Takes Stage 1 output + user portfolio, returns
candidates tagged with gap-fill information + portfolio action items.

#### Step 2a: Load Portfolio State

```python
holdings = repo.get_portfolio_holdings(user_id)  # existing tool
allocation = _compute_sector_allocation(holdings)
watchlist = repo.get_user_tickers(user_id)        # existing PG query
```

Build `portfolio_snapshot` dict (stored in recommendation_runs).

#### Step 2b: Sector Gap Analysis

**Benchmark:** Equal-weight across observed sectors in the universe.
If 10 sectors exist in the 748-stock universe, benchmark is 10% each.

```python
universe_sectors = candidates_df["sector"].value_counts(normalize=True) * 100
user_sectors = {s: w for s, w in allocation.items()}

sector_gaps = {}
for sector in universe_sectors.index:
    benchmark = universe_sectors[sector]
    current = user_sectors.get(sector, 0.0)
    sector_gaps[sector] = current - benchmark
    # Negative = underweight = opportunity
```

Each candidate gets a `sector_gap_pct` value. Stocks in underweight
sectors get a positive gap-fill bonus.

#### Step 2c: Index Tracking Gap

Query `stock_tags` PG table for Nifty 50 constituents:

```python
nifty50_tickers = get_tickers_by_tag("nifty50")   # existing PG query
user_nifty50 = set(holdings_tickers) & set(nifty50_tickers)
missing_nifty50 = set(nifty50_tickers) - set(holdings_tickers)
```

Candidates that are in `missing_nifty50` get an `index_gap = True` flag
and a gap-fill bonus.

#### Step 2d: Market Cap Distribution Gap

**Benchmark:** 60% large cap, 25% mid cap, 15% small cap.

Classify using `market_cap` from `company_info`:
- Large cap: market_cap >= 20,000 Cr (200B INR)
- Mid cap: 5,000 Cr - 20,000 Cr
- Small cap: < 5,000 Cr

Compare user's actual distribution vs benchmark. Candidates in
underweight segments get bonus.

#### Step 2e: Correlation Analysis

Compute pairwise Pearson correlation of user holdings using 1Y daily
returns from OHLCV (same logic as existing `suggest_rebalancing` tool
at `portfolio_tools.py:507-547`).

Flag pairs with correlation > 0.85. These feed into `risk_alert`
recommendations.

#### Step 2f: Concentration Risk Detection

Check existing holdings for:
- Individual position > 20% portfolio weight → `rebalance` candidate
- Sector > 35% portfolio weight → `sector_rotation` candidate
- Market (india/us) > 80% → geographic diversification alert

#### Step 2g: Existing Holdings Scoring

Score each current holding against Stage 1 data:
- Composite score < 30 AND forecast_3m_pct < 0 → tag `exit_reduce`
- Composite score < 40 AND sentiment < -0.3 → tag `risk_alert`
- Composite score > 70 AND underweight (<5%) → tag `hold_accumulate`
- Overweight > 20% → tag `rebalance`

If the holding ticker didn't pass Stage 1 gates (no fresh data), flag
it as `risk_alert` with reason "insufficient data coverage."

#### Step 2h: Gap-Fill Bonus Calculation

For each candidate from Stage 1:

```python
gap_bonus = 0.0

# Sector gap: up to +10 points
if sector_gap_pct < -5:
    gap_bonus += min(10, abs(sector_gap_pct) * 0.5)

# Index tracking: +5 points for missing Nifty 50 constituent
if index_gap:
    gap_bonus += 5.0

# Cap size gap: up to +5 points
if cap_gap_pct < -5:
    gap_bonus += min(5, abs(cap_gap_pct) * 0.3)

gap_adjusted_score = composite_score + gap_bonus
```

Maximum gap bonus: 20 points. This ensures gap-filling candidates
rank higher than equally-scored stocks that don't fill gaps.

#### Step 2i: Tier Assignment

```python
if ticker in holdings_tickers:
    tier = "portfolio"
elif ticker in watchlist_tickers:
    tier = "watchlist"
else:
    tier = "discovery"
```

#### Step 2j: Category Assignment

Based on gap analysis results:

| Condition | Category |
|-----------|----------|
| Holding, composite < 30, forecast negative | `exit_reduce` |
| Holding, weight > 20% | `rebalance` |
| Holding, correlation > 0.85 with another | `risk_alert` |
| Holding, composite > 70, underweight | `hold_accumulate` |
| Watchlist/discovery, fills sector gap | `sector_rotation` |
| Watchlist/discovery, fills index gap | `index_tracking` |
| Watchlist/discovery, high composite | `new_buy` |

#### Output

```python
{
    "portfolio_summary": { ... },      # For LLM context
    "portfolio_actions": [ ... ],      # Holdings tagged for action
    "candidates": [ ... ],            # Top 40 by gap_adjusted_score
    "gap_analysis": {
        "sector_gaps": { ... },
        "nifty50_missing": [ ... ],
        "cap_gaps": { ... },
        "correlation_alerts": [ ... ],
        "concentration_risks": [ ... ]
    }
}
```

Candidates list limited to top 40 by `gap_adjusted_score` to keep
LLM context under 3K tokens.

---

### Stage 3: LLM Reasoning Pass

**Module:** `backend/jobs/recommendation_engine.py`
**Function:** `stage3_llm_reasoning(stage2_output) -> dict`

Single call to `FallbackLLM` (Groq cascade → Anthropic fallback).

#### System Prompt

```
You are a portfolio recommendation engine. Your job is to select
the most impactful recommendations from the candidates provided
and write clear, actionable rationale for each.

RULES:
1. Select 5-8 recommendations total.
2. Include at least 1 from each tier (portfolio/watchlist/discovery)
   IF candidates exist in that tier.
3. Include at least 1 defensive recommendation (risk_alert or
   exit_reduce) if the portfolio has concentration risks or
   deteriorating holdings.
4. Balance offensive (new_buy, accumulate, sector_rotation) and
   defensive (rebalance, risk_alert, exit_reduce) recommendations.
5. Each recommendation MUST explain the specific portfolio impact
   (e.g., "reduces Technology from 38% to ~32%").
6. Assign severity: high (immediate action needed), medium
   (act within the month), low (informational/optional).
7. Do NOT recommend stocks you are not confident about. Fewer
   high-quality recommendations beat many mediocre ones.
8. Reference the data signals (Piotroski, Sharpe, sentiment,
   forecast) in your rationale to ground your reasoning.

OUTPUT: Respond with valid JSON matching the schema exactly.
No markdown, no commentary outside the JSON.
```

#### User Message (Structured Context)

```json
{
  "portfolio_summary": {
    "total_value": 1250000,
    "holdings_count": 12,
    "sector_weights": {"Technology": 38.2, "Financial Services": 5.1, ...},
    "market_weights": {"india": 85, "us": 15},
    "cap_weights": {"largecap": 72, "midcap": 18, "smallcap": 10},
    "nifty50_overlap": 4,
    "concentration_risks": [
      {"type": "stock", "ticker": "TCS.NS", "weight": 22.5},
      {"type": "sector", "sector": "Technology", "weight": 38.2}
    ],
    "correlation_alerts": [
      {"pair": ["TCS.NS", "INFY.NS"], "corr": 0.91}
    ]
  },
  "portfolio_actions": [
    {
      "ticker": "TCS.NS", "category": "rebalance",
      "reason": "22.5% weight exceeds 20% threshold",
      "composite_score": 71, "piotroski": 7, "forecast_3m_pct": 4.2
    }
  ],
  "candidates": [
    {
      "ticker": "HDFCBANK.NS", "tier": "discovery",
      "composite_score": 84.2, "gap_adjusted_score": 96.2,
      "piotroski": 8, "sharpe": 1.4, "sentiment": 0.6,
      "forecast_3m_pct": 12.3, "accuracy_factor": 0.88,
      "sector": "Financial Services",
      "fills_gaps": ["sector underweight -15.2%", "nifty50 missing"],
      "index_tags": ["nifty50", "largecap"],
      "current_price": 1580.0, "target_price": 1774.3
    },
    ...
  ],
  "sector_gaps": {"Financial Services": -15.2, "Healthcare": -8.1, ...}
}
```

#### Expected LLM Output Schema

```json
{
  "recommendations": [
    {
      "ticker": "HDFCBANK.NS",
      "tier": "discovery",
      "category": "new_buy",
      "action": "buy",
      "severity": "high",
      "rationale": "Your Financial Services sector is critically underweight at 5.1% vs 20.3% universe benchmark. HDFCBANK.NS scores Piotroski 8/9 with 1.4 Sharpe ratio and +12.3% forecast upside (88% confidence). Adding it would reduce Technology concentration from 38% to ~33% while adding a Nifty 50 constituent.",
      "expected_impact": "Financial Services +8-10%, Technology -5%, Nifty 50 overlap from 4 to 5"
    }
  ],
  "portfolio_health_assessment": "Your portfolio is Technology-heavy (38.2%) with high TCS-INFY correlation (0.91). Financial Services, Healthcare, and Consumer sectors are significantly underrepresented. Fundamentals are generally strong (avg Piotroski 6.8) but concentration risk is the primary concern.",
  "health_score": 62,
  "health_label": "needs_attention"
}
```

#### LLM Call Configuration

- **Model:** `FallbackLLM` — Groq cascade first (monthly batch is
  cost-sensitive), Anthropic fallback
- **Temperature:** 0.3 (low — we want consistent, grounded output)
- **Max tokens:** 2000 (sufficient for 8 recommendations)
- **Response format:** JSON mode if supported by model, else parse
  with `json.loads()` + retry once on parse failure
- **Token budget:** ~3K input + ~1.5K output = ~4.5K total per user
- **Timeout:** 30s (generous for cascade with retries)

#### Validation & Fallback

After LLM returns:
1. Parse JSON. If invalid, retry once with "Fix your JSON" prompt.
2. Validate each recommendation has required fields.
3. Verify all tickers exist in the candidates list (prevent hallucination).
4. If LLM fails entirely after retries: fall back to deterministic
   selection — top 5 by gap_adjusted_score, with template rationale
   text. Never return empty recommendations.

---

## Recommendation Agent

### Agent Config

**File:** `backend/agents/configs/recommendation.py`

```python
RECOMMENDATION_CONFIG = SubAgentConfig(
    agent_id="recommendation",
    system_prompt=RECOMMENDATION_SYSTEM_PROMPT,
    tools=[
        "generate_recommendations",
        "get_recommendation_history",
        "get_recommendation_performance",
        "get_portfolio_holdings",       # shared
        "get_sector_allocation",        # shared
        "get_risk_metrics",             # shared
    ],
    description="Portfolio recommendation advisor",
)
```

**System prompt key directives:**
- Must call `generate_recommendations` before answering "what should
  I buy/sell" questions
- Must call `get_recommendation_history` for "how did your picks do"
- Can explain individual recommendations in depth using data_signals
- Must use correct currency symbols (INR ₹, USD $)
- Must clarify that recommendations are informational, not financial advice

### Tool Definitions

**File:** `backend/tools/recommendation_tools.py`

#### Tool 1: `generate_recommendations`

```python
@tool
def generate_recommendations(force_refresh: bool = False) -> str:
    """Generate portfolio recommendations using the Smart Funnel
    pipeline. Returns the latest recommendations. If a fresh run
    exists (<24h old), returns cached unless force_refresh=True.

    Source: DuckDB + PostgreSQL + LLM.
    """
```

Logic:
1. Check PG for existing run where `run_date = today` and
   `created_at > now() - 24h`. If exists and not force_refresh,
   return formatted results.
2. Otherwise, run full Smart Funnel pipeline (Stage 1-3).
3. Write `recommendation_runs` + `recommendations` rows to PG.
4. Expire previous runs' active recommendations (`status → expired`).
5. Return formatted markdown with recommendations.

#### Tool 2: `get_recommendation_history`

```python
@tool
def get_recommendation_history(months_back: int = 6) -> str:
    """Fetch past recommendation runs with outcome data.
    Shows hit rate, average return, and adoption rate per run.

    Source: PostgreSQL (read-only).
    """
```

Logic:
1. Query `recommendation_runs` for user, last N months.
2. For each run, join `recommendations` + `recommendation_outcomes`.
3. Compute per-run stats: total recs, acted_on count, outcome
   labels distribution (correct/incorrect/neutral at each checkpoint).
4. Compute aggregate stats: hit rate, avg return, avg excess return
   vs benchmark, adoption rate.
5. Return formatted markdown table.

#### Tool 3: `get_recommendation_performance`

```python
@tool
def get_recommendation_performance(
    run_id: str | None = None,
    ticker: str | None = None,
) -> str:
    """Detailed performance of recommendations. Pass run_id for
    a specific month's run, or ticker for all recommendations
    involving that stock.

    Source: PostgreSQL (read-only).
    """
```

Logic:
1. Query `recommendations` filtered by run_id or ticker.
2. Join `recommendation_outcomes` for 30/60/90d checkpoints.
3. Return detailed view: original rec, signals, each checkpoint's
   return vs benchmark, outcome label.

### Graph Integration

**File:** `backend/agents/graph.py`

Add `recommendation` to the `SUB_AGENTS` list (6th agent). Import
config from `backend/agents/configs/recommendation.py`.

**Router keywords** (in `backend/agents/nodes/guardrail.py`):

```python
RECOMMENDATION_KEYWORDS = {
    "recommend", "recommendation", "suggest", "suggestion",
    "what should i buy", "what should i sell",
    "portfolio advice", "improve my portfolio",
    "how did your picks", "recommendation history",
    "track record", "hit rate",
}
```

If any keyword matches and intent is portfolio-related, route to
`recommendation` agent instead of `portfolio` agent.

---

## Scheduled Jobs

### Job 1: Monthly Recommendation Generator

**File:** `backend/jobs/executor.py`
**Function:** `execute_run_recommendations(run, tickers, force)`

**Job type:** `recommendations`

**Scheduler config:**
- Cron: `0 10 1 * *` (1st of month, 10:00 IST — after overnight
  forecast + sentiment pipelines complete)
- Scope: per-user (iterates all users with portfolio holdings)
- Pipeline: can be step 5 in the `india-daily` pipeline after
  forecast/sentiment/analytics/piotroski, OR standalone monthly job

**Execution flow:**

```python
async def execute_run_recommendations(run, tickers, force):
    # Stage 1: User-independent, cached
    candidates_df = await stage1_prefilter()

    # Get all users with portfolio holdings
    users = await get_users_with_portfolios()

    for user in users:
        try:
            # Stage 2: Per-user gap analysis
            stage2 = await stage2_gap_analysis(
                user.id, candidates_df
            )

            # Stage 3: LLM reasoning
            result = await stage3_llm_reasoning(stage2)

            # Write to PG
            run_id = await write_recommendation_run(
                user.id, stage2, result
            )
            await write_recommendations(run_id, result)

            # Expire old active recs
            await expire_old_recommendations(user.id, run_id)

            # Invalidate Redis cache
            await invalidate_recommendation_cache(user.id)

        except Exception as e:
            logger.error(
                "Recommendation failed for user %s: %s",
                user.id, e,
            )
            # Continue to next user — don't fail batch
```

**Duration estimate:** ~5-10s per user (Stage 2: ~200ms, Stage 3:
~3-5s, PG writes: ~50ms). For 10 users: ~1-2 minutes total.

### Job 2: Daily Outcome Tracker

**File:** `backend/jobs/executor.py`
**Function:** `execute_run_recommendation_outcomes(run, tickers, force)`

**Job type:** `recommendation_outcomes`

**Scheduler config:**
- Cron: `0 11 * * 1-5` (weekdays 11:00 IST, after market open
  and OHLCV refresh)
- Scope: global (checks all active recommendations)

**Execution flow:**

```python
async def execute_run_recommendation_outcomes(run, tickers, force):
    today = date.today()

    # Find recommendations due for a checkpoint
    due_recs = await get_recommendations_due_for_outcome(today)
    # SQL: WHERE status IN ('active', 'acted_on')
    #   AND ticker IS NOT NULL
    #   AND (
    #     (created_at::date + 30 BETWEEN today-2 AND today+2
    #      AND NOT EXISTS 30d outcome)
    #     OR (created_at::date + 60 BETWEEN today-2 AND today+2
    #         AND NOT EXISTS 60d outcome)
    #     OR (created_at::date + 90 BETWEEN today-2 AND today+2
    #         AND NOT EXISTS 90d outcome)
    #   )

    if not due_recs:
        return

    # Batch fetch current prices (DuckDB)
    tickers = list({r.ticker for r in due_recs})
    prices = await batch_get_latest_prices(tickers)

    # Nifty 50 benchmark return
    nifty_prices = await get_nifty50_prices_for_dates(
        [r.created_at.date() for r in due_recs] + [today]
    )

    for rec in due_recs:
        days = (today - rec.created_at.date()).days
        checkpoint = 30 if days < 45 else 60 if days < 75 else 90

        actual = prices.get(rec.ticker)
        if not actual:
            continue

        return_pct = (
            (actual - rec.price_at_rec) / rec.price_at_rec * 100
        )

        # Benchmark: Nifty 50 return over same period
        bench_start = nifty_prices.get(rec.created_at.date())
        bench_end = nifty_prices.get(today)
        bench_return = (
            (bench_end - bench_start) / bench_start * 100
            if bench_start and bench_end else 0.0
        )

        label = _compute_outcome_label(
            rec.action, return_pct
        )

        await insert_recommendation_outcome(
            rec.id, today, checkpoint,
            actual, return_pct, bench_return,
            return_pct - bench_return, label,
        )

    # Expire 90d+ recommendations still active
    await expire_stale_recommendations(today)
```

### User Action Hook

**File:** `backend/portfolio_routes.py` (existing transaction endpoints)

After a successful `POST /v1/users/me/portfolio` (BUY) or when a
SELL transaction is recorded:

```python
# After transaction commit:
await match_recommendation_action(
    user_id=user_id,
    ticker=ticker,
    action="buy" if side == "BUY" else "sell",
)
```

```python
async def match_recommendation_action(user_id, ticker, action):
    """Check if this transaction matches an active recommendation."""
    matching_actions = {
        "buy": ("buy", "accumulate"),
        "sell": ("sell", "reduce"),
    }
    expected = matching_actions.get(action, ())
    if not expected:
        return

    # UPDATE recommendations
    # SET status = 'acted_on', acted_on_date = CURRENT_DATE
    # WHERE run_id IN (
    #   SELECT run_id FROM recommendation_runs
    #   WHERE user_id = %s
    # )
    # AND ticker = %s AND action IN %s AND status = 'active'
    await update_recommendation_status(
        user_id, ticker, expected, "acted_on"
    )
```

---

## API Endpoints

All endpoints in `backend/dashboard_routes.py` (or a new
`backend/recommendation_routes.py` if preferred for separation).

### GET `/v1/dashboard/portfolio/recommendations`

**Auth:** JWT required
**Cache:** `cache:portfolio:recs:{user_id}`, TTL 300s
**Query params:** `market` (optional, `india`/`us`/`all`, default `all`)

**Response model:**

```python
class RecommendationResponse(BaseModel):
    run_id: str
    run_date: str                          # ISO date
    run_type: str                          # scheduled/manual/chat
    health_score: float                    # 0-100
    health_label: str                      # critical/needs_attention/healthy/excellent
    health_assessment: str                 # LLM-generated summary
    recommendations: list[RecommendationItem]
    generated_at: str                      # ISO datetime

class RecommendationItem(BaseModel):
    id: str
    tier: str                              # portfolio/watchlist/discovery
    category: str                          # 7 category types
    ticker: str | None
    company_name: str | None
    action: str                            # buy/sell/reduce/hold/accumulate/rotate/alert
    severity: str                          # high/medium/low
    rationale: str                         # LLM text
    expected_impact: str | None            # Portfolio impact description
    data_signals: dict                     # Raw scores
    price_at_rec: float | None
    target_price: float | None
    expected_return_pct: float | None
    index_tags: list[str]
    status: str                            # active/acted_on/ignored/expired
    acted_on_date: str | None
```

**Logic:** Fetch latest `recommendation_runs` for user. If none exist,
return empty with `health_label = "no_data"`. Join `recommendations`
for that run. Filter by market if specified.

### POST `/v1/dashboard/portfolio/recommendations/refresh`

**Auth:** JWT required
**Rate limit:** 1 per hour per user (slowapi)
**Response:** Same as GET (returns newly generated recommendations)

**Logic:** Trigger full Smart Funnel pipeline with `run_type = "manual"`.
Invalidate Redis cache. Return results.

### GET `/v1/dashboard/portfolio/recommendations/history`

**Auth:** JWT required
**Cache:** `cache:portfolio:recs:history:{user_id}`, TTL 300s
**Query params:** `months_back` (default 6, max 24)

**Response model:**

```python
class RecommendationHistoryResponse(BaseModel):
    runs: list[HistoryRunItem]
    aggregate_stats: AggregateStats

class HistoryRunItem(BaseModel):
    run_id: str
    run_date: str
    health_score: float
    health_label: str
    total_recommendations: int
    acted_on_count: int
    outcomes: OutcomeSummary                # At each checkpoint

class OutcomeSummary(BaseModel):
    checkpoint_30d: CheckpointStats | None
    checkpoint_60d: CheckpointStats | None
    checkpoint_90d: CheckpointStats | None

class CheckpointStats(BaseModel):
    measured_count: int
    correct_count: int
    incorrect_count: int
    neutral_count: int
    avg_return_pct: float
    avg_benchmark_pct: float
    avg_excess_pct: float
    hit_rate_pct: float                    # correct / measured * 100

class AggregateStats(BaseModel):
    total_runs: int
    total_recommendations: int
    overall_hit_rate_30d: float | None
    overall_hit_rate_60d: float | None
    overall_hit_rate_90d: float | None
    overall_avg_return_pct: float | None
    overall_avg_excess_pct: float | None
    adoption_rate_pct: float               # acted_on / total * 100
```

### GET `/v1/dashboard/portfolio/recommendations/{run_id}`

**Auth:** JWT required
**Response:** Full `RecommendationResponse` for that specific run,
including per-recommendation outcomes if available.

### GET `/v1/dashboard/portfolio/recommendations/stats`

**Auth:** JWT required
**Cache:** `cache:portfolio:recs:stats:{user_id}`, TTL 600s

**Response model:**

```python
class RecommendationStatsResponse(BaseModel):
    total_recommendations: int
    total_acted_on: int
    adoption_rate_pct: float
    hit_rate_30d: float | None
    hit_rate_60d: float | None
    hit_rate_90d: float | None
    avg_return_30d: float | None
    avg_return_60d: float | None
    avg_return_90d: float | None
    avg_excess_return_30d: float | None    # vs Nifty 50
    avg_excess_return_60d: float | None
    avg_excess_return_90d: float | None
    best_pick: BestPickItem | None         # Highest return
    worst_pick: BestPickItem | None        # Lowest return
    category_breakdown: dict[str, int]     # Count per category

class BestPickItem(BaseModel):
    ticker: str
    category: str
    return_pct: float
    run_date: str
```

---

## Frontend

### Upgraded Recommendations Widget

**File:** `frontend/components/widgets/RecommendationsWidget.tsx`

Replaces current rule-based widget entirely.

#### Layout

```
┌─────────────────────────────────────────────────────┐
│ Portfolio Health: [██████████░░] 62 — Needs Attention│
│ Last updated: Apr 1, 2026  [🔄 Refresh]             │
├─────────────────────────────────────────────────────┤
│ [All] [Portfolio] [Watchlist] [Discovery]  ← Tier   │
│ [All] [High] [Medium] [Low]               ← Filter │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🔴 HIGH | NEW BUY | Discovery                  │ │
│ │ HDFCBANK.NS — HDFC Bank Ltd         ₹1,580.00  │ │
│ │                                                 │ │
│ │ Your Financial Services sector is critically    │ │
│ │ underweight at 5.1% vs 20.3% benchmark...      │ │
│ │                                                 │ │
│ │ [Piotroski 8] [Sharpe 1.4] [Sentiment +0.6]   │ │
│ │ [Forecast +12.3% ↑88% conf] [Nifty 50]        │ │
│ │                                                 │ │
│ │ Impact: Financial Services +8-10%, Tech -5%     │ │
│ │                                    [View →]     │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟡 MEDIUM | REBALANCE | Portfolio              │ │
│ │ TCS.NS — Tata Consultancy Services  ₹3,450.00  │ │
│ │ ...                                             │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

#### Components

- `RecommendationCard.tsx` — Individual recommendation card with
  tier badge (blue=portfolio, green=watchlist, purple=discovery),
  severity border color (red/amber/blue), signal pills, action button
- `HealthScoreBadge.tsx` — Circular progress indicator with score
  and label. Colors: red (<30), amber (<60), green (<80), blue (>=80)
- `SignalPill.tsx` — Reusable pill component: `[Piotroski 8]` with
  color based on value quality (green if good, red if concerning)

#### SWR Hook

**File:** `frontend/hooks/useDashboardData.ts` (extend existing)

```typescript
export function useRecommendations(market: string) {
  return useSWR<RecommendationResponse>(
    `/dashboard/portfolio/recommendations?market=${market}`,
    apiFetch,
    { refreshInterval: 0 }  // No auto-refresh (monthly data)
  );
}

export function useRecommendationRefresh() {
  // POST trigger, mutates useRecommendations cache on success
}
```

### Recommendation History Tab

**Location:** Analytics > Insights page, new tab after existing tabs.

**Tab label:** "Rec History" (short for space)

**File:** `frontend/components/insights/RecommendationHistoryTab.tsx`

#### Layout

```
┌─────────────────────────────────────────────────────────┐
│ Recommendation Track Record                              │
├──────────────┬──────────────┬───────────────┬───────────┤
│ Hit Rate 30d │ Hit Rate 60d │ Avg Excess    │ Adoption  │
│   68.4%      │   72.1%      │  +3.2% vs N50 │  45.0%    │
├──────────────┴──────────────┴───────────────┴───────────┤
│                                                          │
│ ▼ April 2026 — Health: 62 (Needs Attention)             │
│   8 recommendations | 3 acted on | 2 pending outcome    │
│   ┌─────────────────────────────────────────────────┐   │
│   │ HDFCBANK.NS | New Buy | Discovery               │   │
│   │ 30d: +5.2% (✅ correct) | 60d: pending          │   │
│   │ Benchmark: +2.1% | Excess: +3.1%                │   │
│   └─────────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────────┐   │
│   │ TCS.NS | Rebalance | Portfolio                   │   │
│   │ 30d: -1.8% (⚪ neutral) | 60d: pending          │   │
│   └─────────────────────────────────────────────────┘   │
│                                                          │
│ ▶ March 2026 — Health: 55 (Needs Attention)             │
│   6 recommendations | 4 acted on | 5 outcomes measured  │
│                                                          │
│ ▶ February 2026 — Health: 48 (Needs Attention)          │
│   7 recommendations | 2 acted on | 7 outcomes measured  │
└─────────────────────────────────────────────────────────┘
```

#### Components

- `RecommendationHistoryTab.tsx` — Main tab container with aggregate
  stats KPI cards at top, collapsible monthly run sections below
- `RunHistoryCard.tsx` — Collapsible card for each monthly run
- `OutcomeBadge.tsx` — Green checkmark (correct), red X (incorrect),
  grey circle (neutral), clock (pending)

#### SWR Hook

```typescript
export function useRecommendationHistory(monthsBack: number = 6) {
  return useSWR<RecommendationHistoryResponse>(
    `/dashboard/portfolio/recommendations/history?months_back=${monthsBack}`,
    apiFetch,
    { refreshInterval: 0 }
  );
}

export function useRecommendationStats() {
  return useSWR<RecommendationStatsResponse>(
    `/dashboard/portfolio/recommendations/stats`,
    apiFetch,
    { refreshInterval: 0 }
  );
}
```

### URL Tab Persistence

The Insights page already has URL tab persistence (`?tab=`). Add
`recommendations` as a valid tab value:

```typescript
const VALID_TABS = [
  "screener", "piotroski", "sentiment", "recommendations"
];
```

---

## Alembic Migration

**File:** `backend/db/migrations/versions/e7f8a9b0c1d2_add_recommendation_tables.py`

Single migration creating all 3 tables + indexes.

```python
def upgrade():
    # recommendation_runs
    op.create_table(
        "recommendation_runs",
        sa.Column("run_id", sa.dialects.postgresql.UUID,
                  server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID,
                  sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("run_type", sa.String(20), nullable=False),
        sa.Column("portfolio_snapshot", sa.dialects.postgresql.JSONB,
                  nullable=False),
        sa.Column("health_score", sa.Float, nullable=False),
        sa.Column("health_label", sa.String(20), nullable=False),
        sa.Column("candidates_scanned", sa.Integer, nullable=False),
        sa.Column("candidates_passed", sa.Integer, nullable=False),
        sa.Column("llm_model", sa.String(50)),
        sa.Column("llm_tokens_used", sa.Integer),
        sa.Column("duration_secs", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        schema="stocks",
    )
    op.create_index(
        "ix_rec_runs_user_date", "recommendation_runs",
        ["user_id", sa.text("run_date DESC")],
        schema="stocks",
    )

    # recommendations
    op.create_table(
        "recommendations",
        sa.Column("id", sa.dialects.postgresql.UUID,
                  server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("run_id", sa.dialects.postgresql.UUID,
                  sa.ForeignKey("stocks.recommendation_runs.run_id",
                                ondelete="CASCADE"),
                  nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("category", sa.String(25), nullable=False),
        sa.Column("ticker", sa.String(20)),
        sa.Column("action", sa.String(15), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("expected_impact", sa.Text),
        sa.Column("data_signals", sa.dialects.postgresql.JSONB,
                  nullable=False),
        sa.Column("price_at_rec", sa.Float),
        sa.Column("target_price", sa.Float),
        sa.Column("expected_return_pct", sa.Float),
        sa.Column("index_tags", sa.dialects.postgresql.ARRAY(sa.String)),
        sa.Column("status", sa.String(15), nullable=False,
                  server_default="active"),
        sa.Column("acted_on_date", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        schema="stocks",
    )
    op.create_index(
        "ix_recs_run_id", "recommendations", ["run_id"],
        schema="stocks",
    )
    op.create_index(
        "ix_recs_ticker_status", "recommendations",
        ["ticker", "status"], schema="stocks",
    )
    op.create_index(
        "ix_recs_status_created", "recommendations",
        ["status", "created_at"], schema="stocks",
    )

    # recommendation_outcomes
    op.create_table(
        "recommendation_outcomes",
        sa.Column("id", sa.dialects.postgresql.UUID,
                  server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("recommendation_id", sa.dialects.postgresql.UUID,
                  sa.ForeignKey("stocks.recommendations.id",
                                ondelete="CASCADE"),
                  nullable=False),
        sa.Column("check_date", sa.Date, nullable=False),
        sa.Column("days_elapsed", sa.Integer, nullable=False),
        sa.Column("actual_price", sa.Float, nullable=False),
        sa.Column("return_pct", sa.Float, nullable=False),
        sa.Column("benchmark_return_pct", sa.Float, nullable=False),
        sa.Column("excess_return_pct", sa.Float, nullable=False),
        sa.Column("outcome_label", sa.String(15), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        schema="stocks",
    )
    op.create_index(
        "ix_rec_outcomes_rec_days", "recommendation_outcomes",
        ["recommendation_id", "days_elapsed"],
        unique=True, schema="stocks",
    )


def downgrade():
    op.drop_table("recommendation_outcomes", schema="stocks")
    op.drop_table("recommendations", schema="stocks")
    op.drop_table("recommendation_runs", schema="stocks")
```

---

## ORM Models

**File:** `backend/db/models/recommendation.py`

Three SQLAlchemy 2.0 models:
- `RecommendationRun` — maps to `stocks.recommendation_runs`
- `Recommendation` — maps to `stocks.recommendations`
- `RecommendationOutcome` — maps to `stocks.recommendation_outcomes`

Follow existing patterns in `backend/db/models/scheduler_run.py`:
- `Mapped[]` type annotations
- `mapped_column()` with explicit types
- Relationships with `back_populates`
- `__table_args__ = {"schema": "stocks"}`

Register in `backend/db/models/__init__.py`.

---

## PG Functions

**File:** `backend/db/pg_stocks.py` (extend existing)

New functions following existing `_pg_session()` + NullPool pattern:

```python
def insert_recommendation_run(run_data: dict) -> str:
    """Insert a recommendation run, return run_id."""

def insert_recommendations(run_id: str, recs: list[dict]) -> int:
    """Bulk insert recommendations for a run. Returns count."""

def get_latest_recommendation_run(user_id: str) -> dict | None:
    """Get most recent run for user."""

def get_recommendations_for_run(run_id: str) -> list[dict]:
    """Get all recommendations for a run."""

def get_recommendation_history(
    user_id: str, months_back: int = 6
) -> list[dict]:
    """Get runs with outcome stats for history view."""

def get_recommendation_stats(user_id: str) -> dict:
    """Aggregate stats: hit rates, avg returns, adoption."""

def get_recommendations_due_for_outcome(today: date) -> list:
    """Find recs due for 30/60/90d checkpoint."""

def insert_recommendation_outcome(
    rec_id: str, check_date: date, days: int,
    price: float, ret: float, bench: float,
    excess: float, label: str,
) -> None:
    """Insert an outcome checkpoint row."""

def update_recommendation_status(
    user_id: str, ticker: str,
    actions: tuple, new_status: str,
) -> int:
    """Match user action to active recommendation. Returns updated count."""

def expire_old_recommendations(
    user_id: str, current_run_id: str,
) -> int:
    """Set status=expired on all active recs from prior runs."""

def expire_stale_recommendations(today: date) -> int:
    """Expire active recs older than 90 days."""
```

---

## Redis Cache Keys

| Key pattern | TTL | Invalidated by |
|-------------|-----|----------------|
| `cache:portfolio:recs:{user_id}` | 300s | Manual refresh, new scheduled run |
| `cache:portfolio:recs:history:{user_id}` | 300s | New outcome checkpoint |
| `cache:portfolio:recs:stats:{user_id}` | 600s | New outcome checkpoint |
| `cache:recs:prefilter:{date}` | 3600s | Daily (date changes) |

---

## Testing Strategy

### Unit Tests

| Test | What it validates |
|------|-------------------|
| `test_composite_score_calculation` | All 6 signal normalizations, weights sum to 1.0, edge cases (NaN, zero, negative) |
| `test_accuracy_factor` | MAPE/MAE/RMSE combinations, zero price edge case, clamping |
| `test_gap_analysis_sector` | Sector gap calculation, bonus assignment, underweight/overweight detection |
| `test_gap_analysis_index` | Nifty 50 overlap detection, missing constituent flagging |
| `test_gap_analysis_correlation` | Correlation > 0.85 flagging, pairs dedup |
| `test_tier_assignment` | Holdings → portfolio, watchlist → watchlist, else → discovery |
| `test_category_assignment` | Each of 7 categories triggers correctly |
| `test_outcome_labeling` | buy/sell/hold correct/incorrect/neutral rules |
| `test_action_matching` | BUY transaction matches buy/accumulate recs, SELL matches sell/reduce |
| `test_llm_output_validation` | Valid JSON parsing, ticker hallucination rejection, fallback on parse failure |
| `test_expiration` | Old recommendations expire, 90d+ expire, current run unaffected |

### Integration Tests

| Test | What it validates |
|------|-------------------|
| `test_full_pipeline_e2e` | Stage 1-3 with real DuckDB data, PG writes, response model |
| `test_recommendation_api_endpoints` | All 5 endpoints: auth, cache, response schema |
| `test_manual_refresh_rate_limit` | Rate limit 1/hour enforced |
| `test_outcome_tracker_job` | 30/60/90d checkpoints created correctly |
| `test_action_hook` | Portfolio BUY triggers recommendation status update |

### Minimum coverage

- Happy path for each Stage (1, 2, 3)
- 1 error path per Stage (empty portfolio, no candidates, LLM failure)
- All 7 recommendation categories have at least 1 test case
- All 3 outcome checkpoints (30d, 60d, 90d) tested

---

## File Inventory

New files to create:

| File | Purpose |
|------|---------|
| `backend/db/models/recommendation.py` | 3 ORM models |
| `backend/db/migrations/versions/e7f8a9b0c1d2_add_recommendation_tables.py` | Alembic migration |
| `backend/jobs/recommendation_engine.py` | Smart Funnel pipeline (stages 1-3) |
| `backend/agents/configs/recommendation.py` | Agent config + system prompt |
| `backend/tools/recommendation_tools.py` | 3 new tools |
| `frontend/components/widgets/RecommendationsWidget.tsx` | Upgraded widget (rewrite) |
| `frontend/components/widgets/RecommendationCard.tsx` | Individual card component |
| `frontend/components/widgets/HealthScoreBadge.tsx` | Health score circle |
| `frontend/components/widgets/SignalPill.tsx` | Signal pill component |
| `frontend/components/insights/RecommendationHistoryTab.tsx` | History tab |
| `frontend/components/insights/RunHistoryCard.tsx` | Collapsible run card |
| `frontend/components/insights/OutcomeBadge.tsx` | Outcome indicator |
| `tests/test_recommendation_engine.py` | Unit + integration tests |

Files to modify:

| File | Change |
|------|--------|
| `backend/db/models/__init__.py` | Register 3 new models |
| `backend/db/pg_stocks.py` | Add ~10 PG functions |
| `backend/jobs/executor.py` | Add `recommendations` + `recommendation_outcomes` job types |
| `backend/agents/graph.py` | Register 6th sub-agent |
| `backend/agents/nodes/guardrail.py` | Add recommendation routing keywords |
| `backend/bootstrap.py` | Register 3 new tools |
| `backend/dashboard_routes.py` | Replace recommendation endpoint + add 4 new endpoints |
| `backend/dashboard_models.py` | Add response models |
| `backend/portfolio_routes.py` | Add action matching hook |
| `frontend/hooks/useDashboardData.ts` | Add 3 SWR hooks |
| `frontend/hooks/useInsightsData.ts` | Add history + stats hooks |
| `frontend/lib/types.ts` | Add TypeScript types |
| `frontend/app/(authenticated)/analytics/insights/page.tsx` | Add Rec History tab |

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM hallucinates tickers not in candidates | Recommends non-existent stocks | Post-validation: reject any ticker not in Stage 2 output |
| LLM returns invalid JSON | Pipeline fails | Retry once with correction prompt; fall back to deterministic top-5 |
| Groq rate limit on batch (many users) | Delayed recommendations | Process users sequentially with 2s delay between LLM calls |
| Forecast data stale for some tickers | Weak recommendations | Hard gate: exclude tickers with forecast > 30 days old |
| User has empty portfolio | No gap analysis possible | Return "Add stocks to get recommendations" message, skip pipeline |
| Outcome prices unavailable (delisted/suspended) | Can't measure outcome | Skip outcome row, log warning. Don't count in hit rate. |
| Composite score weights suboptimal | Poor recommendation quality | Store all raw signals in data_signals JSONB for future weight tuning. ML layer (future) can learn optimal weights from outcomes. |

---

## Future: ML Scoring Layer (Research Pending)

The composite score weights (0.25/0.20/0.15/0.20/0.10/0.10) are
manually set in v1. The outcome tracking system generates labeled
training data (correct/incorrect per recommendation with all input
signals stored in `data_signals`).

Once we have 3-6 months of outcome data, an ML model can learn
optimal weights or replace the linear composite with a non-linear
scorer. This plugs into Stage 1 as an additional signal or as a
replacement for the weighted sum.

Research topics (for /sc:research):
- Collaborative filtering for portfolio recommendations
- Gradient-boosted ranking models (LightGBM/XGBoost) for stock scoring
- Reinforcement learning for portfolio optimization
- Feature importance analysis from outcome data

This is explicitly out of scope for v1 but the data model supports it.
