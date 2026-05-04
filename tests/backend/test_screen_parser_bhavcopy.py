"""Unit tests for ScreenQL Sprint-9 extensions.

Covers:
- New bhavcopy / fundamentals_snapshot / promoter / events
  fields registered in FIELD_CATALOG (parse + SQL CTEs).
- LIKE operator (case-insensitive substring on text fields).
- Tables sub-mode (parse_table_query + generate_table_sql).

Pure parser + generator tests — no DuckDB / Iceberg /
network. The screen endpoints' integration is exercised
via curl smoke after backend restart.
"""

from __future__ import annotations

import pytest

from backend.insights.screen_parser import (
    FIELD_CATALOG,
    TABLE_CATALOG,
    TABLE_LIMIT_MAX,
    ScreenQLError,
    generate_sql,
    generate_table_sql,
    parse_query,
    parse_table_query,
)


# ---------------------------------------------------------------
# 1. New fields land in FIELD_CATALOG
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        # Bhavcopy Volume
        "today_vol", "avg_20d_vol",
        "today_x_vol", "x_vol_10d", "x_vol_20d",
        # Bhavcopy Delivery
        "today_dpc", "current_dpc",
        "avg_10d_dpc", "avg_20d_dpc",
        "today_dv", "today_x_dv",
        "x_dv_10d", "x_dv_20d",
        # Fundamentals Snapshot
        "sales_3y_cagr", "prft_3y_cagr",
        "roce", "debt_to_eq", "yoy_qtr_prft",
        # Promoter
        "prom_hld_pct", "pledged_pct", "chng_qoq",
        # Events
        "latest_event_type", "latest_event_date",
    ],
)
def test_new_field_registered(field: str):
    assert field in FIELD_CATALOG, (
        f"{field} missing from FIELD_CATALOG"
    )


def test_new_field_parses_in_screen_query():
    """A query referencing one of the new bhavcopy
    fields parses + generates SQL with the matching
    CTE included."""
    ast = parse_query("today_x_vol > 2")
    gen = generate_sql(ast, page=1, page_size=5)
    assert "nd" in gen.tables_used
    # CTE block should reference the materialized
    # window aggregation
    assert "nd_raw" in gen.sql
    assert "nd_agg" in gen.sql
    # WHERE clause should qualify with nd alias
    assert "nd.today_x_vol" in gen.sql


def test_promoter_field_brings_in_ph_cte():
    ast = parse_query("pledged_pct > 50")
    gen = generate_sql(ast, page=1, page_size=5)
    assert "ph" in gen.tables_used
    assert "promoter_holdings" in gen.sql
    assert "ph.pledged_pct" in gen.sql


def test_events_field_uses_text_op():
    """latest_event_type is TEXT — supports = / != /
    LIKE only."""
    ast = parse_query(
        'latest_event_type = "Dividend"',
    )
    gen = generate_sql(ast, page=1, page_size=5)
    assert "ce" in gen.tables_used
    assert "ce.event_type" in gen.sql


# ---------------------------------------------------------------
# 2. LIKE operator
# ---------------------------------------------------------------


def test_like_operator_parses_for_text_field():
    ast = parse_query('ticker LIKE "RELIA"')
    gen = generate_sql(ast, page=1, page_size=5)
    assert "LIKE LOWER" in gen.sql
    assert "ESCAPE '\\'" in gen.sql
    # Param wraps the bare substring with %s
    assert any(
        isinstance(p, str) and p == "%RELIA%"
        for p in gen.params
    ), gen.params


def test_like_operator_rejected_on_number_field():
    with pytest.raises(ScreenQLError) as exc:
        parse_query("market_cap LIKE \"foo\"")
    assert "Cannot use LIKE" in str(exc.value)


def test_like_operator_escapes_metacharacters():
    """User-supplied % / _ are escaped so they don't
    behave as SQL LIKE wildcards."""
    ast = parse_query('ticker LIKE "100%"')
    gen = generate_sql(ast, page=1, page_size=5)
    # Raw % becomes \% inside the wrapping %...%
    found = [
        p for p in gen.params
        if isinstance(p, str) and "100" in p
    ]
    assert found, gen.params
    assert "\\%" in found[0]


# ---------------------------------------------------------------
# 3. Tables sub-mode — parse + generate
# ---------------------------------------------------------------


def test_table_catalog_includes_aa_tables():
    for t in (
        "nse_delivery",
        "fundamentals_snapshot",
        "corporate_events",
        "promoter_holdings",
        "ohlcv",
        "dividends",
        "quarterly_results",
    ):
        assert t in TABLE_CATALOG


def test_table_query_parses_known_column():
    ast = parse_table_query(
        "delivery_pct > 70", "nse_delivery",
    )
    assert ast is not None


def test_table_query_rejects_unknown_table():
    with pytest.raises(ScreenQLError):
        parse_table_query(
            "delivery_pct > 70", "secret_table",
        )


def test_table_query_rejects_unknown_column():
    with pytest.raises(ScreenQLError) as exc:
        parse_table_query(
            "fake_col > 1", "nse_delivery",
        )
    assert "Unknown column" in str(exc.value)


def test_empty_where_returns_none_ast():
    assert parse_table_query("", "nse_delivery") is None
    assert (
        parse_table_query("   \n  ", "nse_delivery")
        is None
    )


def test_generate_table_sql_caps_limit():
    gen = generate_table_sql(
        "nse_delivery",
        None,
        limit=10_000,
    )
    assert (
        f"LIMIT ${len(gen.params) - 1}" in gen.sql
    )
    assert TABLE_LIMIT_MAX in gen.params


def test_generate_table_sql_emits_single_table_select():
    """Tables-mode SQL has no WITH clause and no JOIN
    — single-table SELECT only."""
    ast = parse_table_query(
        "delivery_pct > 70", "nse_delivery",
    )
    gen = generate_table_sql(
        "nse_delivery",
        ast,
        sort_by="delivery_pct",
        sort_dir="desc",
        limit=50,
    )
    assert "WITH" not in gen.sql
    assert "JOIN" not in gen.sql
    assert "FROM nse_delivery" in gen.sql
    assert "delivery_pct DESC" in gen.sql
    assert "LIMIT" in gen.sql


def test_generate_table_sql_with_ticker_scope():
    """Ticker scope filter is appended even when WHERE
    is empty (general users see only watchlist
    + holdings)."""
    gen = generate_table_sql(
        "nse_delivery",
        None,
        limit=20,
        ticker_filter=["RELIANCE.NS", "TCS.NS"],
    )
    assert "ticker IN (" in gen.sql
    assert "RELIANCE.NS" in gen.params
    assert "TCS.NS" in gen.params


def test_table_query_text_op_validation():
    """LIKE allowed on text columns; > rejected."""
    parse_table_query(
        'ticker LIKE "RELIA"', "nse_delivery",
    )
    with pytest.raises(ScreenQLError) as exc:
        parse_table_query(
            'ticker > "AAPL"', "nse_delivery",
        )
    assert "Cannot use" in str(exc.value)
