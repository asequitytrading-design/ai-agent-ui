"""Tests for dashboard API endpoints.

Exercises ``/v1/dashboard/*`` routes: watchlist, forecasts,
analysis, and LLM usage.  All Iceberg access is mocked via
:func:`unittest.mock.patch`.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from auth.dependencies import get_current_user
from auth.models import UserContext


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _make_app():
    """Build a FastAPI app with mocked infra deps."""
    mock_registry = MagicMock()
    mock_registry.get.return_value = None
    mock_registry.list_agents.return_value = []

    mock_executor = MagicMock()

    mock_settings = MagicMock()
    mock_settings.agent_timeout_seconds = 30
    mock_settings.groq_model_tiers = ""

    with (
        patch(
            "routes.create_auth_router",
            return_value=APIRouter(),
        ),
        patch(
            "routes.get_ticker_router",
            return_value=APIRouter(),
        ),
        patch("paths.ensure_dirs"),
        patch(
            "paths.AVATARS_DIR",
            new=Path("/tmp/test_avatars"),
        ),
        patch("routes.StaticFiles"),
    ):
        from routes import create_app

        app = create_app(
            mock_registry,
            mock_executor,
            mock_settings,
        )

    return app


_TEST_USER = UserContext(
    user_id="test-user-1",
    email="test@example.com",
    role="user",
)


@pytest.fixture()
def client():
    """TestClient with auth override."""
    app = _make_app()
    app.dependency_overrides[get_current_user] = (
        lambda: _TEST_USER
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def unauthed_client():
    """TestClient without auth override (401 expected)."""
    app = _make_app()
    return TestClient(app)


# ---------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------


class TestWatchlist:
    """GET /v1/dashboard/watchlist."""

    def test_requires_auth(self, unauthed_client):
        """No auth token -> 401."""
        resp = unauthed_client.get(
            "/v1/dashboard/watchlist",
        )
        assert resp.status_code == 401

    @patch(
        "dashboard_routes._helpers._get_repo",
    )
    def test_empty_tickers(
        self, mock_repo, client,
    ):
        """No linked tickers -> empty response."""
        mock_repo.return_value.get_user_tickers \
            .return_value = []

        resp = client.get("/v1/dashboard/watchlist")

        assert resp.status_code == 200
        data = resp.json()
        assert data["tickers"] == []

    @patch("dashboard_routes._get_stock_repo")
    @patch(
        "dashboard_routes._helpers._get_repo",
    )
    def test_with_data(
        self, mock_user_repo, mock_stock_repo, client,
    ):
        """One ticker returns price + change."""
        mock_user_repo.return_value.get_user_tickers \
            .return_value = ["AAPL"]

        prices = [148.0, 149.0, 150.0, 151.0, 152.0]
        df = pd.DataFrame({"close": prices})

        repo_inst = mock_stock_repo.return_value
        repo_inst.get_dashboard_ohlcv.return_value = df
        repo_inst.get_dashboard_company_info \
            .return_value = {
                "company_name": "Apple Inc.",
            }

        resp = client.get("/v1/dashboard/watchlist")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tickers"]) == 1
        ticker = data["tickers"][0]
        assert ticker["ticker"] == "AAPL"
        assert ticker["company_name"] == "Apple Inc."
        assert ticker["current_price"] == 152.0
        assert ticker["previous_close"] == 151.0
        assert ticker["change"] == 1.0


# ---------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------


class TestForecasts:
    """GET /v1/dashboard/forecasts/summary."""

    @patch(
        "dashboard_routes._helpers._get_repo",
    )
    def test_empty(self, mock_repo, client):
        """No linked tickers -> empty forecasts."""
        mock_repo.return_value.get_user_tickers \
            .return_value = []

        resp = client.get(
            "/v1/dashboard/forecasts/summary",
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["forecasts"] == []

    @patch("dashboard_routes._get_stock_repo")
    @patch(
        "dashboard_routes._helpers._get_repo",
    )
    def test_with_data(
        self, mock_user_repo, mock_stock_repo, client,
    ):
        """Forecast run with 3-month target."""
        mock_user_repo.return_value.get_user_tickers \
            .return_value = ["AAPL"]

        df = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "run_date": "2026-03-01",
                    "current_price_at_run": 150.0,
                    "sentiment": "bullish",
                    "target_3m_date": "2026-06-01",
                    "target_3m_price": 165.0,
                    "target_3m_pct_change": 10.0,
                    "target_3m_lower": 155.0,
                    "target_3m_upper": 175.0,
                    "mae": 2.5,
                    "rmse": 3.1,
                },
            ]
        )

        repo_inst = mock_stock_repo.return_value
        repo_inst.get_dashboard_forecast_runs \
            .return_value = df

        resp = client.get(
            "/v1/dashboard/forecasts/summary",
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["forecasts"]) == 1
        fc = data["forecasts"][0]
        assert fc["ticker"] == "AAPL"
        assert len(fc["targets"]) >= 1
        assert fc["targets"][0]["horizon_months"] == 3
        assert fc["targets"][0]["target_price"] == 165.0


# ---------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------


class TestAnalysis:
    """GET /v1/dashboard/analysis/latest."""

    @patch(
        "dashboard_routes._helpers._get_repo",
    )
    def test_empty(self, mock_repo, client):
        """No linked tickers -> empty analyses."""
        mock_repo.return_value.get_user_tickers \
            .return_value = []

        resp = client.get(
            "/v1/dashboard/analysis/latest",
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["analyses"] == []

    @patch("dashboard_routes._get_stock_repo")
    @patch(
        "dashboard_routes._helpers._get_repo",
    )
    def test_with_data(
        self, mock_user_repo, mock_stock_repo, client,
    ):
        """Analysis row with RSI signal."""
        mock_user_repo.return_value.get_user_tickers \
            .return_value = ["AAPL"]

        df = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "analysis_date": "2026-03-15",
                    "rsi_signal": "Bullish reversal",
                    "rsi_14": 32.5,
                    "macd_signal_text": None,
                    "macd": None,
                    "sma_50_signal": None,
                    "sma_50": None,
                    "sma_200_signal": None,
                    "sma_200": None,
                    "sharpe_ratio": 1.23,
                    "annualized_return_pct": 12.5,
                    "annualized_volatility_pct": 18.3,
                    "max_drawdown_pct": -8.2,
                },
            ]
        )

        repo_inst = mock_stock_repo.return_value
        repo_inst.get_dashboard_analysis.return_value = df

        resp = client.get(
            "/v1/dashboard/analysis/latest",
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["analyses"]) == 1
        analysis = data["analyses"][0]
        assert analysis["ticker"] == "AAPL"
        assert len(analysis["signals"]) == 1
        sig = analysis["signals"][0]
        assert sig["name"] == "RSI 14"
        assert sig["signal"] == "Bullish"
        assert analysis["sharpe_ratio"] == 1.23


# ---------------------------------------------------------------
# LLM Usage
# ---------------------------------------------------------------


class TestLLMUsage:
    """GET /v1/dashboard/llm-usage."""

    @patch("dashboard_routes._get_stock_repo")
    def test_returns_structure(
        self, mock_stock_repo, client,
    ):
        """Verify response fields."""
        repo_inst = mock_stock_repo.return_value
        repo_inst.get_dashboard_llm_usage.return_value = {
            "total_requests": 42,
            "total_cost_usd": 1.23,
            "avg_latency_ms": 250.0,
            "models": [
                {
                    "model": "llama-3.3-70b",
                    "provider": "groq",
                    "request_count": 42,
                    "total_tokens": 50000,
                    "estimated_cost_usd": 1.23,
                },
            ],
            "daily_trend": [],
        }

        resp = client.get("/v1/dashboard/llm-usage")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 42
        assert data["total_cost_usd"] == 1.23
        assert len(data["models"]) == 1
        assert data["models"][0]["model"] == "llama-3.3-70b"

    @patch("dashboard_routes._get_stock_repo")
    def test_superuser_sees_all(
        self, mock_stock_repo,
    ):
        """Superuser passes user_id=None."""
        su_user = UserContext(
            user_id="admin-1",
            email="admin@example.com",
            role="superuser",
        )
        app = _make_app()
        app.dependency_overrides[get_current_user] = (
            lambda: su_user
        )

        repo_inst = mock_stock_repo.return_value
        repo_inst.get_dashboard_llm_usage.return_value = {
            "total_requests": 0,
            "total_cost_usd": 0,
            "models": [],
        }

        tc = TestClient(app)
        resp = tc.get("/v1/dashboard/llm-usage")

        assert resp.status_code == 200
        repo_inst.get_dashboard_llm_usage.assert_called_once()
        call_kwargs = (
            repo_inst.get_dashboard_llm_usage.call_args
        )
        assert call_kwargs.kwargs.get("user_id") is None

        app.dependency_overrides.clear()
