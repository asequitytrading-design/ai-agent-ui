# ScreenQL

ScreenQL is a text-based stock query language exposed on the
**Insights** tab of `/analytics/insights?tab=screenql`. Pro
and superuser tiers can query 55 fields across the joined
latest-per-ticker view of `company_info`, `analysis_summary`,
`piotroski_scores`, `forecast_runs`, `sentiment_scores`,
`quarterly_results` plus the four Sprint-9 Advanced
Analytics tables. A separate **Tables sub-mode** lets users
query a single Iceberg table directly using the same DSL.

Parser + SQL generator lives in
`backend/insights/screen_parser.py`. Endpoint surface in
`backend/insights_routes.py` (lines 1877+).

---

## Grammar

```
query        := condition (connector condition)*
condition    := field operator value
              | "(" query ")"
operator     := ">" | "<" | ">=" | "<=" | "=" | "!="
              | "LIKE"        (text fields only)
              | "CONTAINS"    (array fields — tags)
connector    := "AND" | "OR"  (newlines = implicit AND)
value        := number | "string in double quotes"
```

- `LIKE` is **case-insensitive substring** with `%` and `_`
  in user input escaped on the way in. So
  `ticker LIKE "RELIA"` matches RELIANCE.NS, RELINFRA.NS,
  RELIGARE.NS, etc. — no need to write `%`.
- Hard cap: 20 conditions per query; query string ≤ 2000
  chars.
- Newlines are implicit `AND`. Use explicit `OR` when
  needed.

### Examples

```
# Simple
pe_ratio < 15 AND market_cap > 50000

# With LIKE
ticker LIKE "RELIA" AND profit_margins > 10

# Bhavcopy delivery breakout
today_x_vol > 2 AND today_dpc > 50 AND piotroski_score >= 6

# Substring sector filter
sector = "Healthcare" AND sales_3y_cagr > 0.20

# Promoter conviction
prom_hld_pct > 60 AND pledged_pct < 5 AND chng_qoq > 0
```

---

## Field catalog (55 fields)

Categories — mostly mirror the columns surfaced by
`/advanced-analytics` so you can move from a report to a
cross-ticker query without re-learning names.

### Identity (6)
`ticker` (TEXT — supports LIKE), `company_name`, `sector`,
`industry`, `market`, `currency`

### Valuation (9)
`market_cap`, `pe_ratio`, `peg_ratio`, `peg_ratio_yf`,
`price_to_book`, `dividend_yield`, `current_price`,
`week_52_high`, `week_52_low`

### Profitability (6)
`profit_margins`, `earnings_growth`, `revenue_growth`,
`revenue`, `net_income`, `eps` (eps_diluted)

### Risk (5)
`sharpe_ratio`, `annualized_return_pct`,
`annualized_volatility_pct`, `max_drawdown_pct`, `beta`

### Technical (5)
`rsi_14`, `rsi_signal`, `macd_signal`, `sma_200_signal`,
`sentiment_score`

### Quality (3)
`piotroski_score`, `piotroski_label`, `forecast_confidence`

### Forecast (3)
`target_3m_pct`, `target_6m_pct`, `target_9m_pct`

### Bhavcopy Volume (5) — *Sprint 9*
`today_vol`, `avg_20d_vol`, `today_x_vol` (× 20d),
`x_vol_10d`, `x_vol_20d`

### Bhavcopy Delivery (8) — *Sprint 9*
`today_dpc`, `current_dpc`, `avg_10d_dpc`, `avg_20d_dpc`,
`today_dv` (deliverable_qty), `today_x_dv`, `x_dv_10d`,
`x_dv_20d`

### Fundamentals Snapshot (5) — *Sprint 9*
`sales_3y_cagr`, `prft_3y_cagr`, `roce`, `debt_to_eq`,
`yoy_qtr_prft`

### Promoter (3) — *Sprint 9*
`prom_hld_pct`, `pledged_pct`, `chng_qoq`

### Events (2) — *Sprint 9*
`latest_event_type` (TEXT — `=`/`!=`/`LIKE`),
`latest_event_date` (TEXT, ISO 8601)

> The Sprint-9 fields are computed from `nse_delivery`
> (rolling 25-day window aggregates per ticker, anchored
> to `MAX(date) FROM nse_delivery`),
> `fundamentals_snapshot`, `promoter_holdings`, and
> `corporate_events` — same source data as the AA reports.

---

## API

### `POST /v1/insights/screen`

```json
{
  "query": "today_x_vol > 2 AND today_dpc > 50",
  "page": 1,
  "page_size": 25,
  "sort_by": null,
  "sort_dir": "desc",
  "display_columns": ["today_x_vol", "today_dpc", "piotroski_score"]
}
```

Response: `{rows, total, page, page_size, columns_used,
excluded_null_count}`. Cache key: SHA256 of
`query + page + sort + dcols + user_id`, TTL 300s.

### `GET /v1/insights/screen/fields`

Returns the 55-field catalog as
`[{name, label, type, category}, ...]`. Used by the
ScreenQL textarea autocomplete on the frontend.

---

## Tables sub-mode

Switch to **Tables** in the ScreenQL UI to query a single
Iceberg table directly. Same DSL grammar, different field
namespace — fields are the columns of the picked table.

Whitelisted tables (`TABLE_CATALOG` in `screen_parser.py`):

| Table | Columns |
|---|---|
| `nse_delivery` | ticker, date, deliverable_qty, delivery_pct, traded_qty, traded_value |
| `fundamentals_snapshot` | ticker, snapshot_date, sales_3y_cagr, prft_3y_cagr, sales_5y_cagr, prft_5y_cagr, yoy_qtr_prft, yoy_qtr_sales, roce, debt_to_eq |
| `corporate_events` | ticker, event_date, event_type, event_label |
| `promoter_holdings` | ticker, quarter_end, prom_hld_pct, pledged_pct, chng_qoq, source |
| `ohlcv` | ticker, date, open, high, low, close, volume |
| `dividends` | ticker, ex_date, amount |
| `quarterly_results` | ticker, quarter_end, statement_type, revenue, net_income, eps_diluted |

### `GET /v1/insights/screen/tables`

Returns the catalog as
`[{name, iceberg, columns: [{name, type}, ...]}, ...]`.

### `POST /v1/insights/screen/table`

```json
{
  "table": "nse_delivery",
  "where": "delivery_pct > 70 AND ticker LIKE \"RELIA\"",
  "sort_by": "delivery_pct",
  "sort_dir": "desc",
  "limit": 100,
  "offset": 0
}
```

- Hard cap: `limit ≤ 1000`. Default 100.
- `where` is optional; empty → `SELECT *` capped by `LIMIT`.
- Date columns are typed TEXT and cast to VARCHAR in the
  SELECT — use `LIKE "2026-04"` for substring time
  filters in v1 (numeric range comes later).
- Ticker scope filter (`ticker IN (scoped_tickers)`) is
  injected by the endpoint for general users; pro and
  superuser see the full table.
- Cache key: SHA256 of full request body, TTL 300s.

---

## Out of scope (deferred)

- Aggregation operators (SUM / AVG / GROUP BY) — Tables
  mode is single-row-per-row only.
- Cross-table JOINs in Tables mode — pick one table.
- Free-form SQL editor — explicitly rejected during scope
  clarification (Tables sub-mode replaces it).
- Saved queries / query history — current URL persistence
  (`?tab=screenql&q=...&mode=tables`) is the persistence
  story.

## Tests

`tests/backend/test_screen_parser_bhavcopy.py` covers field
registration, LIKE op (parse, SQL emission, metacharacter
escaping), Tables sub-mode (parse, generator, LIMIT cap,
ticker scope, text-op validation). 38 cases pass in 0.1 s.
Combined with the existing `test_screen_parser_peg.py` and
`test_screen_parser_market.py`: 67/67 parser tests green.
