"""Bhavcopy ingestion smoke (AA-12).

Stubs the NSE source + Iceberg repo to assert
:func:`backend.pipeline.jobs.bhavcopy.run_bhavcopy`:

- Fetches once from :class:`NseSource`.
- Forwards the resulting DataFrame to
  ``StockRepository.insert_nse_delivery`` exactly once
  (single bulk Iceberg commit per day, §4.1 #2).
- Returns a summary dict with ``status="ok"``,
  ``rows=<count>``, and the requested date.
- Returns ``status="skipped"`` on an empty bhavcopy
  (weekend / holiday).
- Returns ``status="failed"`` and surfaces the error
  string when fetch raises ``SourceError``.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pandas as pd
import pytest

import backend.pipeline.jobs.bhavcopy as bjob
import backend.tools._stock_shared as shared
from backend.pipeline.sources.base import (
    SourceError,
    SourceErrorCategory,
)


def _bhavcopy_df(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [f"X{i}.NS" for i in range(n)],
            "date": [date(2026, 5, 1)] * n,
            "deliverable_qty": [1000, 2000, 3000],
            "delivery_pct": [10.0, 20.0, 30.0],
            "traded_qty": [10000, 20000, 30000],
            "traded_value": [100000.0, 200000.0, 300000.0],
        }
    )


class _FakeNseSource:
    def __init__(
        self,
        df: pd.DataFrame | None = None,
        *,
        raises: Exception | None = None,
    ):
        self._df = df
        self._raises = raises
        self.calls: list[date] = []

    async def fetch_bhavcopy(self, d: date) -> pd.DataFrame:
        self.calls.append(d)
        if self._raises is not None:
            raise self._raises
        return self._df if self._df is not None else pd.DataFrame()


class _FakeRepo:
    def __init__(self):
        self.insert_calls: list[tuple[pd.DataFrame, date]] = []

    def insert_nse_delivery(self, df: pd.DataFrame, d: date) -> int:
        self.insert_calls.append((df.copy(), d))
        return len(df)


@pytest.fixture
def stub_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRepo:
    repo = _FakeRepo()
    monkeypatch.setattr(shared, "_require_repo", lambda: repo)
    return repo


def _patch_source(monkeypatch: pytest.MonkeyPatch, src: _FakeNseSource):
    monkeypatch.setattr(bjob, "NseSource", lambda: src)


def test_run_bhavcopy_happy_path_emits_one_iceberg_commit(
    monkeypatch: pytest.MonkeyPatch,
    stub_repo: _FakeRepo,
):
    df = _bhavcopy_df(3)
    src = _FakeNseSource(df=df)
    _patch_source(monkeypatch, src)

    result = asyncio.run(bjob.run_bhavcopy(date(2026, 5, 1)))

    assert result == {"date": "2026-05-01", "status": "ok", "rows": 3}
    assert src.calls == [date(2026, 5, 1)]
    assert len(stub_repo.insert_calls) == 1
    assert len(stub_repo.insert_calls[0][0]) == 3
    assert stub_repo.insert_calls[0][1] == date(2026, 5, 1)


def test_run_bhavcopy_empty_df_marks_skipped_no_write(
    monkeypatch: pytest.MonkeyPatch,
    stub_repo: _FakeRepo,
):
    src = _FakeNseSource(df=pd.DataFrame())
    _patch_source(monkeypatch, src)

    result = asyncio.run(bjob.run_bhavcopy(date(2026, 5, 2)))

    assert result == {"date": "2026-05-02", "status": "skipped", "rows": 0}
    assert stub_repo.insert_calls == []


def test_run_bhavcopy_source_error_is_surfaced(
    monkeypatch: pytest.MonkeyPatch,
    stub_repo: _FakeRepo,
):
    src = _FakeNseSource(
        raises=SourceError(
            SourceErrorCategory.RATE_LIMIT,
            "NSE rate-limited",
        )
    )
    _patch_source(monkeypatch, src)

    result = asyncio.run(bjob.run_bhavcopy(date(2026, 5, 3)))

    assert result["status"] == "failed"
    assert result["date"] == "2026-05-03"
    assert result["rows"] == 0
    assert "NSE rate-limited" in result["error"]
    assert stub_repo.insert_calls == []
