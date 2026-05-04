"""Unit tests for ETF classification (ASETPLTFRM-357 item 5).

Covers:

- ``_detect_ticker_type`` correctly classifies an ETF symbol
  when ``_load_etf_symbols`` returns it.
- ``_detect_ticker_type`` defaults to ``"stock"`` for an
  unknown symbol.
- ``_filter_tickers`` with ``ticker_type="etf"`` keeps only
  the registry entries whose ``ticker_type == "etf"`` —
  i.e. the AA ``?ticker_type=etf`` filter is wired through.
"""

from __future__ import annotations

import pytest

import backend.advanced_analytics_routes as aar
import backend.tools._stock_registry as sr


@pytest.fixture(autouse=True)
def _reset_etf_cache():
    """Wipe the module-level ETF symbol cache before each test
    so monkeypatched ``_load_etf_symbols`` results don't leak
    between test cases."""
    sr._etf_symbols = None
    yield
    sr._etf_symbols = None


def test_detect_ticker_type_classifies_etf(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sr, "_load_etf_symbols", lambda: {"NIFTYBEES"},
    )
    assert sr._detect_ticker_type("NIFTYBEES.NS") == "etf"


def test_detect_ticker_type_defaults_to_stock(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sr, "_load_etf_symbols", lambda: {"NIFTYBEES"},
    )
    assert sr._detect_ticker_type("RELIANCE.NS") == "stock"


def test_filter_tickers_etf_returns_only_etfs(
    monkeypatch: pytest.MonkeyPatch,
):
    class _StubRepo:
        def get_all_registry(self):
            return {
                "NIFTYBEES.NS": {"ticker_type": "etf"},
                "GOLDBEES.NS": {"ticker_type": "etf"},
                "RELIANCE.NS": {"ticker_type": "stock"},
                "TCS.NS": {"ticker_type": "stock"},
            }

    monkeypatch.setattr(aar, "_get_stock_repo", lambda: _StubRepo())

    tickers = [
        "NIFTYBEES.NS",
        "GOLDBEES.NS",
        "RELIANCE.NS",
        "TCS.NS",
    ]
    out = aar._filter_tickers(tickers, "all", "etf")
    assert sorted(out) == ["GOLDBEES.NS", "NIFTYBEES.NS"]
