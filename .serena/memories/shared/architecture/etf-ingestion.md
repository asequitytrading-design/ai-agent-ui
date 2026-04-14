# NSE ETF Ingestion

## Overview
54 NSE ETFs ingested via standard pipeline infrastructure (seed CSV + bulk-download).

## ETF Categories
| Category | Count | Examples |
|----------|-------|---------|
| Broad Market (Nifty/Sensex) | 10 | NIFTYBEES, SETFNIF50, HDFCNIFTY |
| Next50/Midcap/Smallcap | 6 | JUNIORBEES, MID150BEES, SMALLCAP |
| Sectoral | 12 | BANKBEES, ITBEES, PHARMABEES, INFRABEES |
| Factor/Smart Beta | 8 | MOM50, MOMENTUM, ALPHAETF, MOVALUE |
| Gold/Silver | 8 | GOLDBEES, GOLD1, SILVERBEES, HDFCGOLD |
| International | 5 | MON100, MONQ50, MAFANG, MASPTOP50 |
| Debt/Liquid | 4 | LIQUIDBEES, LIQUID, GILT5YBEES |
| Thematic | 1 | EVINDIA |

## Seed File
`data/universe/nse_etfs.csv` — columns: symbol, name, isin (empty), exchange (NSE), series (EQ), sector, industry, tags

## Pipeline Support
| Pipeline | ETF Support | Notes |
|----------|-------------|-------|
| data_refresh (OHLCV) | Yes | Included in daily refresh via registry |
| compute_analytics | Yes | Pure technical analysis on OHLCV |
| run_sentiment | Yes | Headlines + market fallback scores |
| run_forecasts | Yes | Prophet on OHLCV + regressors |
| run_piotroski | No | No quarterly financials for ETFs |

## ETF Data Characteristics (from yfinance)
- quoteType: EQUITY (not ETF — NSE ETFs listed as equity)
- No sector/industry, no quarterly financials, no balance sheet
- Have: P/E ratio (equity ETFs), 52w high/low, volume, OHLCV
- Some have dividends (e.g., LIQUIDBEES)
- company_info sparse — names available but limited metadata

## Ingestion Commands
```bash
# Seed stock_master (run inside container)
docker compose exec backend python -m backend.pipeline.runner seed --csv data/universe/nse_etfs.csv

# Bulk download (use symbols WITHOUT .NS — script auto-appends)
docker compose exec backend python -m backend.pipeline.runner bulk-download --tickers NIFTYBEES,GOLDBEES,... --period 10y
```

## Key Gotcha
The `--tickers` flag in bulk-download expects symbols WITHOUT `.NS` suffix. The script resolves `yf_ticker` from stock_master (which auto-derives as `{symbol}.NS`). Passing `NIFTYBEES.NS` results in double suffix `NIFTYBEES.NS.NS`.
