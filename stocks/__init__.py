"""Iceberg-backed storage layer for stock market data.

This package provides table schemas, a repository class, and a backfill
script for migrating all stock data from flat JSON/parquet files into an
Apache Iceberg warehouse shared with the ``auth`` namespace.

Namespace: ``stocks`` (alongside ``auth`` in the same SQLite catalog).

Tables
------
- ``stocks.registry``              — one row per ticker; fetch metadata
- ``stocks.company_info``          — append-only snapshots; latest by ``fetched_at DESC``
- ``stocks.ohlcv``                 — OHLCV price history; partitioned by ticker
- ``stocks.dividends``             — dividend payments; one row per (ticker, ex_date)
- ``stocks.technical_indicators``  — computed indicators; partitioned by ticker
- ``stocks.analysis_summary``      — daily analysis snapshots per ticker
- ``stocks.forecast_runs``         — Prophet run metadata + accuracy + targets
- ``stocks.forecasts``             — full Prophet output series; partitioned by (ticker, horizon_months)

Usage::

    from stocks.repository import StockRepository

    repo = StockRepository()
    repo.upsert_registry("AAPL", last_fetch_date=date.today(), ...)
    df = repo.get_ohlcv("AAPL")
"""
