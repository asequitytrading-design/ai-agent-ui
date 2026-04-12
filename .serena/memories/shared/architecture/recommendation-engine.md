# LLM Portfolio Recommendation Engine (ASETPLTFRM-298)

## Status: Implemented (Apr 12, 2026) — 15 commits on feature/sprint6

## Architecture: Smart Funnel (3 stages)

### Stage 1: DuckDB Pre-Filter (user-independent, 1h cache)
- File: `backend/jobs/recommendation_engine.py`
- Single CTE query joins: piotroski_scores, analysis_summary, sentiment_scores, forecast_runs, ohlcv
- Hard gates: Piotroski >= 4, volume >= 10K, forecast within 30d, sentiment within 7d, MAPE < 80
- 6-factor composite score (0-100): Piotroski 25%, Sharpe 20%, momentum 15%, accuracy-adjusted forecast 20%, sentiment 10%, technical 10%
- Accuracy factor: `0.5*mape_f + 0.3*mae_f + 0.2*rmse_f` discounts unreliable forecasts
- Output: ~100-200 candidates

### Stage 2: Portfolio Gap Analysis (per-user)
- Sector gaps vs universe distribution
- Nifty 50 index tracking (stock_tags PG table)
- Market cap distribution vs 60/25/15 benchmark
- Correlation alerts > 0.85 on holdings
- Gap-fill bonus: up to +20 points (sector 10, index 5, cap 5)
- Tier assignment: portfolio > watchlist > discovery
- Output: top 40 candidates + portfolio actions

### Stage 3: LLM Reasoning (Groq cascade, temp 0.3)
- Structured JSON prompt with portfolio summary + 40 candidates
- Validation: reject hallucinated tickers, check required fields
- Deterministic fallback: top 5 by gap-adjusted score if LLM fails
- Health score: base 70, penalties for concentration/correlation/low diversification, bonus for Nifty50 overlap

## Database (3 PG tables in stocks schema)
- `recommendation_runs`: run metadata + portfolio snapshot JSONB
- `recommendations`: individual recs with tier/category/severity + data_signals JSONB
- `recommendation_outcomes`: append-only 30/60/90d checkpoints with benchmark

## 7 Recommendation Categories
rebalance, exit_reduce, hold_accumulate, new_buy, sector_rotation, risk_alert, index_tracking

## Recommendation Agent (6th LangGraph sub-agent)
- Config: `backend/agents/configs/recommendation.py`
- Tools: generate_recommendations, get_recommendation_history, get_recommendation_performance + 3 shared portfolio tools
- Router: 14 keywords in `router_node.py` intent map

## Scheduler Jobs
- `recommendations`: monthly batch (Stage 1 cached, per-user Stage 2+3)
- `recommendation_outcomes`: daily price check + outcome labeling

## API Endpoints (5)
- GET/POST /v1/dashboard/portfolio/recommendations (list + refresh)
- GET history, stats, {run_id}
- Routes: `backend/recommendation_routes.py`
- Models: `backend/recommendation_models.py`

## Frontend
- Upgraded RecommendationsWidget: HealthScoreBadge, SignalPill, RecommendationCard
- Rec History tab on Insights page (KPI cards + collapsible timeline)
- Hooks: useRecommendations, useRecommendationHistory, useRecommendationStats

## Outcome Tracking
- Per-recommendation lifecycle: active → acted_on/ignored → expired
- Action hook: portfolio BUY/SELL auto-matches active recommendations
- Outcome labels: correct (>2%), incorrect (<-2%), neutral for buy; inverse for sell
- Benchmark: Nifty 50 comparison

## Key Files
| File | Purpose |
|------|---------|
| `backend/jobs/recommendation_engine.py` | Smart Funnel stages 1-3 |
| `backend/db/models/recommendation.py` | 3 ORM models |
| `backend/tools/recommendation_tools.py` | 3 agent tools |
| `backend/agents/configs/recommendation.py` | Agent config |
| `backend/recommendation_routes.py` | 5 API endpoints |
| `frontend/components/widgets/RecommendationsWidget.tsx` | Dashboard widget |
| `frontend/components/insights/RecommendationHistoryTab.tsx` | History tab |
