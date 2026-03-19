# Portfolio Management Framework

## Status: MVP delivered (Mar 19, 2026) — ASETPLTFRM-118

## Data Model
Append-only transactions table: `stocks.portfolio_transactions`
- transaction_id (UUID), user_id, ticker, side (BUY/SELL/DIVIDEND/SPLIT)
- quantity, price, currency (USD/INR), market (us/india)
- trade_date, fees, notes, created_at
- All fields optional (PyArrow compat — required=False in Iceberg schema)

## Current Holdings (computed on read)
GROUP BY (user_id, ticker), SUM quantities, weighted avg price.
Only tickers from registry allowed (MVP). Enriched with current price from OHLCV.

## API Endpoints
- GET /v1/users/me/portfolio — computed holdings + totals per currency
- POST /v1/users/me/portfolio — add BUY transaction
- PUT /v1/users/me/portfolio/{transaction_id} — edit price/qty/date
- DELETE /v1/users/me/portfolio/{transaction_id} — remove

## Frontend Components
- `usePortfolio` hook (SWR + CRUD mutations) in hooks/usePortfolio.ts
- `AddStockModal` — searchable ticker dropdown, qty, price, date
- `WatchlistWidget` — 2-tab (Portfolio | Watchlist)
  - Tab switch auto-selects first ticker for signals widget
  - Portfolio rows clickable with selection highlight
- `HeroSection` — portfolio value per currency, total P&L (current - invested)
  - Welcome: "Welcome back, Abhay!" (first name, gradient, text-3xl)
  - Quick actions navigate to pages (not chat)

## Hero Card P&L
Shows total gain/loss = (current value - invested) per currency.
NOT daily change. Separate INR and USD values.

## Navigation
- Hero Analyze → /analytics/analysis (forces Analysis tab via URL ?tab=)
- Hero Forecast → /analytics/analysis?tab=forecast
- Hero Compare → /analytics/analysis?tab=compare
- Hero Link Ticker → /analytics/marketplace
- Sidebar Analysis → uses saved preference (ticker, tab from usePreferences)

## Future Phases
- Phase 2: Sell transactions, FIFO lot matching, realized P&L
- Phase 3: Dividend tracking, stock splits
- Phase 4: XIRR/CAGR, benchmark comparison, portfolio performance chart
- Phase 5: Asset allocation, rebalancing alerts, portfolio forecast
- Backlog: Multiple portfolios (Retirement, Trading)
