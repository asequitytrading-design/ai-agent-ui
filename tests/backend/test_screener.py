"""Integration tests for Piotroski screen orchestrator."""

import pandas as pd

from backend.pipeline.screener.screen import (
    _aggregate_annual,
)


class TestAggregateAnnual:
    """Tests for _aggregate_annual()."""

    def test_empty_df(self):
        """Empty DataFrame -> empty dict."""
        df = pd.DataFrame()
        assert _aggregate_annual(df) == {}

    def test_merges_statements(self):
        """Income + balance + cashflow merge by year."""
        rows = [
            {
                "statement_type": "income",
                "fiscal_year": 2025,
                "quarter_end": "2025-03-31",
                "revenue": 100,
                "net_income": 20,
                "gross_profit": 50,
                "operating_cashflow": None,
                "total_assets": None,
                "total_debt": None,
                "current_assets": None,
                "current_liabilities": None,
                "shares_outstanding": None,
            },
            {
                "statement_type": "balance",
                "fiscal_year": 2025,
                "quarter_end": "2025-03-31",
                "revenue": None,
                "net_income": None,
                "gross_profit": None,
                "operating_cashflow": None,
                "total_assets": 1000,
                "total_debt": 200,
                "current_assets": 500,
                "current_liabilities": 300,
                "shares_outstanding": 1_000_000,
            },
            {
                "statement_type": "cashflow",
                "fiscal_year": 2025,
                "quarter_end": "2025-03-31",
                "revenue": None,
                "net_income": None,
                "gross_profit": None,
                "operating_cashflow": 150,
                "total_assets": None,
                "total_debt": None,
                "current_assets": None,
                "current_liabilities": None,
                "shares_outstanding": None,
            },
        ]
        df = pd.DataFrame(rows)
        result = _aggregate_annual(df)
        assert 2025 in result
        y = result[2025]
        assert y["revenue"] == 100
        assert y["net_income"] == 20
        assert y["total_assets"] == 1000
        assert y["operating_cashflow"] == 150
        assert y["shares_outstanding"] == 1_000_000

    def test_sums_quarterly_income(self):
        """4 quarters of income are summed."""
        rows = []
        for q in range(1, 5):
            rows.append(
                {
                    "statement_type": "income",
                    "fiscal_year": 2025,
                    "quarter_end": (f"2025-{q * 3:02d}-28"),
                    "revenue": 100,
                    "net_income": 25,
                    "gross_profit": 50,
                    "operating_cashflow": None,
                    "total_assets": None,
                    "total_debt": None,
                    "current_assets": None,
                    "current_liabilities": None,
                    "shares_outstanding": None,
                }
            )
        df = pd.DataFrame(rows)
        result = _aggregate_annual(df)
        assert result[2025]["revenue"] == 400
        assert result[2025]["net_income"] == 100
