# Stock Chart — Support & Resistance Lines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render six horizontal S/R price lines (3 support + 3 resistance) on the candle pane of the stock analysis chart, behind a single toggle in the Indicators dropdown, with right-edge tier+price tags (`R1 2580`, `S1 2210`, …).

**Architecture:** Extend the existing `/v1/dashboard/chart/indicators` endpoint with two `list[float]` fields populated from `_analyse_price_movement` (already produces them). On the frontend, extend `IndicatorVisibility`, draw lines via TradingView's `createPriceLine()` API (already used for RSI 70/30 references), and surface a `Support/Resistance` checkbox in the existing Indicators menu. No schema changes, no new endpoint, no new cache key.

**Tech Stack:** FastAPI + Pydantic 2 (backend), Next.js 16 + TradingView lightweight-charts (frontend), pytest (backend tests), Vitest (frontend unit), Playwright (E2E).

**Spec:** `docs/superpowers/specs/2026-05-05-stock-chart-support-resistance-design.md`

---

## File Map

**Modify:**
- `backend/dashboard_models.py` — extend `IndicatorsResponse` with two list fields.
- `backend/dashboard_routes.py` — call `_analyse_price_movement` in the `/chart/indicators` handler.
- `tests/backend/test_dashboard_routes.py` — extend `TestChartIndicators` (4 cases).
- `frontend/components/charts/StockChart.types.ts` — add `supportResistance: boolean`.
- `frontend/components/charts/StockChart.tsx` — accept new props, draw lines, clean up on toggle off.
- `frontend/app/(authenticated)/analytics/analysis/page.tsx` — fetch new fields, pass props, add Indicators-menu entry.
- `e2e/tests/frontend/analytics-stock.spec.ts` — add S/R toggle scenario.
- `PROGRESS.md` — dated session entry.

**Create:**
- `frontend/tests/StockChart.priceLines.test.tsx` — Vitest unit covering S/R rendering + cleanup.

---

## Pre-flight

- [ ] **Verify branch** — already on `feature/stock-chart-sr-lines` (created during brainstorm). If not:
  ```bash
  git checkout feature/stock-chart-sr-lines || git checkout -b feature/stock-chart-sr-lines dev
  ```

- [ ] **Smoke-run the existing dashboard tests** before touching anything, so any later failure is unambiguously yours.

  Run:
  ```bash
  python -m pytest tests/backend/test_dashboard_routes.py::TestChartIndicators -v
  ```

  Note the current pass/fail status of `test_happy_path` and `test_empty_data` — both should pass. If `test_happy_path` already fails (the existing test mocks `_get_stock_repo.get_technical_indicators` but the route calls `compute_indicators` from `tools._analysis_shared`, which loads OHLCV via `repo.get_ohlcv`), record the baseline so you can preserve current behavior. Do **not** fix the legacy mock as part of this work.

- [ ] **Confirm services running** (so manual smoke at the end works without surprises):
  ```bash
  ./run.sh status
  ```

  Expected: `backend`, `frontend`, `postgres`, `redis` all green. If any are down: `./run.sh start`.

---

## Task 1: Backend — extend `IndicatorsResponse` model

**Files:**
- Modify: `backend/dashboard_models.py:224-228`

- [ ] **Step 1: Add two fields to `IndicatorsResponse`**

  Edit `backend/dashboard_models.py`. Replace the existing class definition with:

  ```python
  class IndicatorsResponse(BaseModel):
      ticker: str
      data: list[IndicatorPoint] = Field(
          default_factory=list,
      )
      support_levels: list[float] = Field(
          default_factory=list,
      )
      resistance_levels: list[float] = Field(
          default_factory=list,
      )
  ```

  Default to empty list (not `None`) so the frontend contract is "always an array, possibly empty".

- [ ] **Step 2: Lint the model file**

  Run:
  ```bash
  black backend/dashboard_models.py && \
    isort backend/dashboard_models.py --profile black && \
    flake8 backend/dashboard_models.py
  ```

  Expected: no output (clean).

- [ ] **Step 3: Commit**

  ```bash
  git add backend/dashboard_models.py
  git commit -m "$(cat <<'EOF'
  feat(api): add support_levels and resistance_levels to IndicatorsResponse

  Extends the chart indicators Pydantic model with two new optional list
  fields so the existing endpoint can carry S/R levels without a new
  route. Defaults to empty list — backward compatible with frontends
  that ignore them.

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 2: Backend — populate fields in `/chart/indicators`

**Files:**
- Modify: `backend/dashboard_routes.py:1162-1237`

- [ ] **Step 1: Add the `_analyse_price_movement` call site**

  In `backend/dashboard_routes.py`, locate the `get_chart_indicators` handler. After the existing `df = compute_indicators(t_upper)` call (≈line 1194) and the `if df is None or df.empty` early return, **and** after the existing `points = []` loop populates `points`, compute the levels and pass them into `IndicatorsResponse`.

  Replace the block from the `compute_indicators` call through the cache-write/return with:

  ```python
          # Compute indicators on-the-fly from OHLCV
          # (~200ms per ticker, cached 300s in Redis).
          from tools._analysis_shared import (
              compute_indicators,
          )
          from tools._analysis_movement import (
              _analyse_price_movement,
          )

          df = compute_indicators(t_upper)

          if df is None or df.empty:
              return IndicatorsResponse(
                  ticker=t_upper,
              )

          points: list[IndicatorPoint] = []
          for idx, row in df.iterrows():
              points.append(
                  IndicatorPoint(
                      date=str(idx.date()),
                      sma_50=_safe(row.get("SMA_50")),
                      sma_200=_safe(
                          row.get("SMA_200"),
                      ),
                      ema_20=_safe(row.get("EMA_20")),
                      rsi_14=_safe(row.get("RSI_14")),
                      macd=_safe(row.get("MACD")),
                      macd_signal=_safe(
                          row.get("MACD_Signal"),
                      ),
                      macd_hist=_safe(
                          row.get("MACD_Hist"),
                      ),
                      bb_upper=_safe(
                          row.get("BB_Upper"),
                      ),
                      bb_lower=_safe(
                          row.get("BB_Lower"),
                      ),
                  )
              )

          movement = _analyse_price_movement(df)
          support_levels = [
              float(v)
              for v in movement.get("support_levels", [])
          ]
          resistance_levels = [
              float(v)
              for v in movement.get("resistance_levels", [])
          ]

          result = IndicatorsResponse(
              ticker=t_upper,
              data=points,
              support_levels=support_levels,
              resistance_levels=resistance_levels,
          )
          cache.set(
              cache_key,
              result.model_dump_json(),
              TTL_STABLE,
          )
          return result
  ```

  Key points:
  - The lazy `from tools._analysis_movement import _analyse_price_movement` import keeps cold-start cost on `dashboard_routes` import unchanged.
  - The `float(v)` coercion converts `numpy.float64` (which `nsmallest` / `nlargest` produce) to plain Python `float` so Pydantic serialization stays clean.
  - The existing `if df is None or df.empty` early return path still returns `IndicatorsResponse(ticker=...)`, which now defaults `support_levels` / `resistance_levels` to `[]` — exactly what we want for unknown tickers.

- [ ] **Step 2: Lint the route file**

  ```bash
  black backend/dashboard_routes.py && \
    isort backend/dashboard_routes.py --profile black && \
    flake8 backend/dashboard_routes.py
  ```

  Expected: no output. If isort suggests moving the new `_analyse_price_movement` import to the top of the file, decline — the lazy import inside the handler is intentional (matches the existing `compute_indicators` import pattern right above it).

- [ ] **Step 3: Restart the backend** (CLAUDE.md §6.2 — Pydantic response_model changed)

  ```bash
  docker compose restart backend
  sleep 5
  ```

- [ ] **Step 4: Manual smoke**

  ```bash
  ACCESS=$(jq -r '.cookies[]|select(.name=="access_token").value' \
    e2e/.auth/superuser.json)
  curl -s -H "Cookie: access_token=$ACCESS" \
    "http://localhost:8181/v1/dashboard/chart/indicators?ticker=RELIANCE.NS" \
    | jq '{ticker, support_levels, resistance_levels, n_points: (.data|length)}'
  ```

  Expected: `support_levels` and `resistance_levels` each contain 3 floats; `n_points` ≥ 200. If you see two empty arrays for a known-good ticker, check that `_analyse_price_movement(df)` is being called after `df` is non-empty.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/dashboard_routes.py
  git commit -m "$(cat <<'EOF'
  feat(dashboard): include S/R levels in /chart/indicators response

  Calls _analyse_price_movement once per request (operates on the same
  DataFrame already in memory) and passes the resulting top-3 lows /
  top-3 highs through to IndicatorsResponse. Cost: ~1ms per request,
  +80 bytes payload, no new Iceberg or DuckDB I/O. Reuses the existing
  cache:chart:indicators:{ticker} Redis key.

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 3: Backend — pytest coverage for new fields

**Files:**
- Modify: `tests/backend/test_dashboard_routes.py` (`TestChartIndicators` class, ≈line 693)

- [ ] **Step 1: Add four test methods to `TestChartIndicators`**

  Append the following methods to the existing `TestChartIndicators` class (after the existing `test_happy_path` and `test_empty_data` — keep those untouched). Patch the source module per CLAUDE.md §4.2 #16:

  ```python
      @patch(
          "tools._analysis_movement._analyse_price_movement",
      )
      @patch("tools._analysis_shared.compute_indicators")
      @patch("dashboard_routes.get_cache")
      def test_returns_sr_levels(
          self,
          mock_cache_fn,
          mock_compute,
          mock_movement,
          client,
      ):
          """S/R levels appear in response when OHLCV exists."""
          import pandas as pd

          mock_compute.return_value = pd.DataFrame(
              [{"Close": 2500.0}],
          )
          mock_movement.return_value = {
              "support_levels": [1950.0, 2080.0, 2210.0],
              "resistance_levels": [
                  2840.0, 2710.0, 2580.0,
              ],
          }

          cache = MagicMock()
          cache.get.return_value = None
          mock_cache_fn.return_value = cache

          resp = client.get(
              "/v1/dashboard/chart/indicators"
              "?ticker=RELIANCE.NS",
          )

          assert resp.status_code == 200
          body = resp.json()
          assert body["support_levels"] == [
              1950.0, 2080.0, 2210.0,
          ]
          assert body["resistance_levels"] == [
              2840.0, 2710.0, 2580.0,
          ]

      @patch(
          "tools._analysis_movement._analyse_price_movement",
      )
      @patch("tools._analysis_shared.compute_indicators")
      @patch("dashboard_routes.get_cache")
      def test_short_history_returns_partial_levels(
          self,
          mock_cache_fn,
          mock_compute,
          mock_movement,
          client,
      ):
          """Newly-listed ticker may yield <3 levels — frontend tolerates."""
          import pandas as pd

          mock_compute.return_value = pd.DataFrame(
              [{"Close": 100.0}],
          )
          mock_movement.return_value = {
              "support_levels": [95.0],
              "resistance_levels": [105.0, 110.0],
          }

          cache = MagicMock()
          cache.get.return_value = None
          mock_cache_fn.return_value = cache

          resp = client.get(
              "/v1/dashboard/chart/indicators"
              "?ticker=NEW.NS",
          )

          assert resp.status_code == 200
          body = resp.json()
          assert body["support_levels"] == [95.0]
          assert body["resistance_levels"] == [105.0, 110.0]

      @patch("tools._analysis_shared.compute_indicators")
      @patch("dashboard_routes.get_cache")
      def test_empty_ohlcv_returns_empty_levels(
          self,
          mock_cache_fn,
          mock_compute,
          client,
      ):
          """Unknown ticker — both arrays empty, 200 OK."""
          mock_compute.return_value = None

          cache = MagicMock()
          cache.get.return_value = None
          mock_cache_fn.return_value = cache

          resp = client.get(
              "/v1/dashboard/chart/indicators"
              "?ticker=UNKNOWN.NS",
          )

          assert resp.status_code == 200
          body = resp.json()
          assert body["support_levels"] == []
          assert body["resistance_levels"] == []

      @patch(
          "tools._analysis_movement._analyse_price_movement",
      )
      @patch("tools._analysis_shared.compute_indicators")
      @patch("dashboard_routes.get_cache")
      def test_cache_hit_skips_recompute(
          self,
          mock_cache_fn,
          mock_compute,
          mock_movement,
          client,
      ):
          """Second request served from Redis — no recompute."""
          cached = (
              '{"ticker":"RELIANCE.NS","data":[],'
              '"support_levels":[1950.0,2080.0,2210.0],'
              '"resistance_levels":'
              '[2840.0,2710.0,2580.0]}'
          )
          cache = MagicMock()
          cache.get.return_value = cached
          mock_cache_fn.return_value = cache

          resp = client.get(
              "/v1/dashboard/chart/indicators"
              "?ticker=RELIANCE.NS",
          )

          assert resp.status_code == 200
          body = resp.json()
          assert body["support_levels"] == [
              1950.0, 2080.0, 2210.0,
          ]
          mock_compute.assert_not_called()
          mock_movement.assert_not_called()
  ```

- [ ] **Step 2: Run only the new tests**

  ```bash
  python -m pytest \
    tests/backend/test_dashboard_routes.py::TestChartIndicators::test_returns_sr_levels \
    tests/backend/test_dashboard_routes.py::TestChartIndicators::test_short_history_returns_partial_levels \
    tests/backend/test_dashboard_routes.py::TestChartIndicators::test_empty_ohlcv_returns_empty_levels \
    tests/backend/test_dashboard_routes.py::TestChartIndicators::test_cache_hit_skips_recompute \
    -v
  ```

  Expected: 4 PASSED. If `test_returns_sr_levels` fails because the `_safe` indicator iteration crashes on the mocked one-row DataFrame, fall back to a richer mock DF — see below.

  Fallback if mocked DF is too thin:
  ```python
  mock_compute.return_value = pd.DataFrame(
      [
          {"Close": 2500.0, "SMA_50": None,
           "SMA_200": None, "EMA_20": None,
           "RSI_14": None, "MACD": None,
           "MACD_Signal": None, "MACD_Hist": None,
           "BB_Upper": None, "BB_Lower": None},
      ],
      index=pd.DatetimeIndex(["2024-01-01"]),
  )
  ```

- [ ] **Step 3: Run the full `TestChartIndicators` class to confirm no regression**

  ```bash
  python -m pytest \
    tests/backend/test_dashboard_routes.py::TestChartIndicators -v
  ```

  Expected: all tests pass — including the two existing ones (whose status you recorded in pre-flight). If the legacy `test_happy_path` was failing before, it should still be failing — do NOT fix it as part of this PR.

- [ ] **Step 4: Lint the test file**

  ```bash
  black tests/backend/test_dashboard_routes.py && \
    isort tests/backend/test_dashboard_routes.py --profile black && \
    flake8 tests/backend/test_dashboard_routes.py
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add tests/backend/test_dashboard_routes.py
  git commit -m "$(cat <<'EOF'
  test(dashboard): cover S/R levels in /chart/indicators

  Adds 4 cases: happy path, short history (partial arrays), empty OHLCV,
  and cache-hit short-circuit. Patches at source module per CLAUDE.md
  §4.2 #16.

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 4: Frontend — extend `IndicatorVisibility`

**Files:**
- Modify: `frontend/components/charts/StockChart.types.ts`

- [ ] **Step 1: Add `supportResistance` to the type and default**

  Replace the file contents with:

  ```typescript
  // Types + defaults extracted from StockChart.tsx so consumers
  // (e.g. analysis/page.tsx) can reference them without pulling
  // `lightweight-charts` (~150 KB) into the initial bundle.

  export type ChartInterval = "D" | "W" | "M";

  export interface IndicatorVisibility {
    sma50: boolean;
    sma200: boolean;
    bollinger: boolean;
    volume: boolean;
    rsi: boolean;
    macd: boolean;
    supportResistance: boolean;
  }

  export const DEFAULT_INDICATORS: IndicatorVisibility = {
    sma50: true,
    sma200: true,
    bollinger: false,
    volume: false,
    rsi: true,
    macd: true,
    supportResistance: false,
  };
  ```

- [ ] **Step 2: Type-check**

  ```bash
  cd frontend && npx tsc --noEmit
  ```

  Expected: no errors. If `tsc` complains about another file constructing `IndicatorVisibility` literal that's now missing `supportResistance`, fix that call site to add `supportResistance: false` in the same commit. Run `grep -rn "IndicatorVisibility\|DEFAULT_INDICATORS" frontend/` from the repo root to find them.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/components/charts/StockChart.types.ts
  git commit -m "$(cat <<'EOF'
  feat(chart): add supportResistance flag to IndicatorVisibility

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 5: Frontend — render S/R lines in `StockChart`

**Files:**
- Modify: `frontend/components/charts/StockChart.tsx`

- [ ] **Step 1: Extend the chart component props**

  In `frontend/components/charts/StockChart.tsx`, find the `StockChart` component's props interface (search for `interface StockChartProps` or, if it's inline, the function signature). Add two optional fields:

  ```typescript
  supportLevels?: number[];
  resistanceLevels?: number[];
  ```

  Update the function signature to destructure them with empty-array defaults:

  ```typescript
  export function StockChart({
    ohlcv,
    indicators,
    isDark,
    height,
    interval,
    visibleIndicators,
    onCrosshairMove,
    supportLevels = [],
    resistanceLevels = [],
  }: StockChartProps) {
  ```

- [ ] **Step 2: Add the price-line render effect**

  Find the existing chart-build effect (the big `useEffect` that creates `chart`, `candleSeries`, RSI series with its 70/30 reference lines, etc.). At the **end** of that effect — after all existing series are created and before the cleanup return — add:

  ```typescript
      // ── Support / Resistance overlays ──────────────────
      const srLineRefs: ReturnType<
        typeof candleSeries.createPriceLine
      >[] = [];

      if (visibleIndicators.supportResistance) {
        // Tier R1/S1 = nearest to latest close, R3/S3 = furthest.
        // Backend returns supports ASC and resistances DESC, so
        // the LAST element of each array is closest to the
        // boundary between supports and resistances. The chart's
        // latest close anchors the partition.
        const lastClose =
          ohlcv.length > 0
            ? ohlcv[ohlcv.length - 1].close
            : null;

        const supports = (supportLevels ?? [])
          .filter((v) =>
            lastClose === null ? true : v <= lastClose,
          )
          .slice()
          .sort((a, b) => b - a); // nearest-below first

        const resistances = (resistanceLevels ?? [])
          .filter((v) =>
            lastClose === null ? true : v >= lastClose,
          )
          .slice()
          .sort((a, b) => a - b); // nearest-above first

        supports.forEach((price, idx) => {
          srLineRefs.push(
            candleSeries.createPriceLine({
              price,
              color: "#10b981",
              lineWidth: 1,
              lineStyle: 2, // LineStyle.Dashed
              axisLabelVisible: true,
              title: `S${idx + 1}`,
            }),
          );
        });

        resistances.forEach((price, idx) => {
          srLineRefs.push(
            candleSeries.createPriceLine({
              price,
              color: "#ef4444",
              lineWidth: 1,
              lineStyle: 2, // LineStyle.Dashed
              axisLabelVisible: true,
              title: `R${idx + 1}`,
            }),
          );
        });
      }
  ```

- [ ] **Step 3: Extend the cleanup function**

  Inside the same effect, find the existing cleanup `return () => { ... }` block. Add a price-line teardown loop **before** the existing `chart.remove()` call:

  ```typescript
      return () => {
        srLineRefs.forEach((line) => {
          try {
            candleSeries.removePriceLine(line);
          } catch {
            // chart may already be disposed
          }
        });
        // … existing chart.remove() etc. …
      };
  ```

- [ ] **Step 4: Add `supportLevels`, `resistanceLevels`, and `visibleIndicators.supportResistance` to the effect's dependency array**

  Find the dependency array at the bottom of the chart-build `useEffect` and add the three new dependencies. Order doesn't matter; placement next to the other `visibleIndicators.*` deps keeps the diff small.

- [ ] **Step 5: Type-check + lint**

  ```bash
  cd frontend && npx tsc --noEmit && npx eslint components/charts/StockChart.tsx
  ```

  Expected: no errors.

- [ ] **Step 6: Manual smoke** — start (or rely on already-running) frontend, open `http://localhost:3000/analytics/analysis?ticker=RELIANCE.NS`. Toggle `Support/Resistance` on (this checkbox doesn't exist yet — Task 7 wires it; for now manually edit `localStorage` or temporarily flip `DEFAULT_INDICATORS.supportResistance` to `true` to verify lines render). Revert the temporary flip before committing.

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/components/charts/StockChart.tsx
  git commit -m "$(cat <<'EOF'
  feat(chart): render support/resistance price lines on candle pane

  Adds optional supportLevels + resistanceLevels props. When the
  supportResistance flag in IndicatorVisibility is on, draws up to 6
  dashed horizontal lines via createPriceLine (same API as existing
  RSI 70/30 references) — green/S below the latest close, red/R above,
  tier label R1/R2/R3 + S1/S2/S3 by proximity. Lines torn down on
  toggle off via removePriceLine.

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 6: Frontend — Vitest unit for chart price lines

**Files:**
- Create: `frontend/tests/StockChart.priceLines.test.tsx`

- [ ] **Step 1: Inspect the existing Vitest setup once**

  ```bash
  cat frontend/vitest.config.ts
  ls frontend/tests/__mocks__ 2>/dev/null || echo "no __mocks__ dir"
  grep -l "lightweight-charts" frontend/tests/*.test.* 2>/dev/null || \
    echo "no existing lightweight-charts mocks — we'll add one inline"
  ```

  Note the test file extension convention (`.test.tsx`) and whether the project uses `vi.mock()` inline.

- [ ] **Step 2: Write the test**

  Create `frontend/tests/StockChart.priceLines.test.tsx`:

  ```tsx
  import { describe, it, expect, vi, beforeEach } from "vitest";
  import { render, cleanup } from "@testing-library/react";

  // Capture every createPriceLine + removePriceLine call across the
  // mocked candle series so we can assert on titles + counts.
  const priceLineSpy = vi.fn();
  const removePriceLineSpy = vi.fn();
  const fakePriceLine = (cfg: { title?: string }) => ({
    options: () => cfg,
  });

  vi.mock("lightweight-charts", () => {
    const candleSeries = {
      setData: vi.fn(),
      createPriceLine: vi.fn((cfg) => {
        priceLineSpy(cfg);
        return fakePriceLine(cfg);
      }),
      removePriceLine: vi.fn((line) => {
        removePriceLineSpy(line);
      }),
      priceScale: () => ({ applyOptions: vi.fn() }),
    };
    const lineSeries = {
      setData: vi.fn(),
      createPriceLine: vi.fn(() => ({ options: () => ({}) })),
      priceScale: () => ({ applyOptions: vi.fn() }),
    };
    const chart = {
      addSeries: vi.fn((kind) =>
        kind?.toString?.().includes?.("Candlestick")
          ? candleSeries
          : lineSeries,
      ),
      timeScale: () => ({
        applyOptions: vi.fn(),
        fitContent: vi.fn(),
        subscribeVisibleLogicalRangeChange: vi.fn(),
      }),
      subscribeCrosshairMove: vi.fn(),
      remove: vi.fn(),
      applyOptions: vi.fn(),
    };
    return {
      createChart: vi.fn(() => chart),
      AreaSeries: "AreaSeries",
      CandlestickSeries: "CandlestickSeries",
      LineSeries: "LineSeries",
      HistogramSeries: "HistogramSeries",
      ColorType: { Solid: "solid" },
      CrosshairMode: { Normal: 0 },
    };
  });

  // eslint-disable-next-line import/first
  import { StockChart } from "@/components/charts/StockChart";

  const ohlcv = [
    { date: "2024-12-01", open: 100, high: 105,
      low:  95, close: 100, volume: 1_000_000 },
    { date: "2024-12-02", open: 100, high: 110,
      low:  98, close: 105, volume: 1_000_000 },
  ];
  const indicators: never[] = [];

  const baseProps = {
    ohlcv,
    indicators,
    isDark: false,
    height: 600,
    interval: "D" as const,
    onCrosshairMove: vi.fn(),
  };

  describe("StockChart S/R price lines", () => {
    beforeEach(() => {
      priceLineSpy.mockClear();
      removePriceLineSpy.mockClear();
      cleanup();
    });

    it("draws 3 supports + 3 resistances when toggle is on", () => {
      render(
        <StockChart
          {...baseProps}
          supportLevels={[80, 90, 95]}
          resistanceLevels={[120, 115, 110]}
          visibleIndicators={{
            sma50: false,
            sma200: false,
            bollinger: false,
            volume: false,
            rsi: false,
            macd: false,
            supportResistance: true,
          }}
        />,
      );

      const titles = priceLineSpy.mock.calls.map(
        ([cfg]) => cfg.title,
      );
      expect(titles.sort()).toEqual(
        ["R1", "R2", "R3", "S1", "S2", "S3"],
      );
    });

    it("draws zero S/R lines when toggle is off", () => {
      render(
        <StockChart
          {...baseProps}
          supportLevels={[80, 90, 95]}
          resistanceLevels={[120, 115, 110]}
          visibleIndicators={{
            sma50: false,
            sma200: false,
            bollinger: false,
            volume: false,
            rsi: false,
            macd: false,
            supportResistance: false,
          }}
        />,
      );

      const titles = priceLineSpy.mock.calls.map(
        ([cfg]) => cfg.title,
      );
      expect(
        titles.filter(
          (t) => /^[RS][123]$/.test(t ?? ""),
        ),
      ).toEqual([]);
    });

    it("removes all S/R lines on unmount", () => {
      const { unmount } = render(
        <StockChart
          {...baseProps}
          supportLevels={[80, 90, 95]}
          resistanceLevels={[120, 115, 110]}
          visibleIndicators={{
            sma50: false,
            sma200: false,
            bollinger: false,
            volume: false,
            rsi: false,
            macd: false,
            supportResistance: true,
          }}
        />,
      );
      unmount();
      expect(removePriceLineSpy).toHaveBeenCalledTimes(6);
    });
  });
  ```

  Notes for the engineer:
  - The `vi.mock("lightweight-charts", …)` block is inline because the codebase does not yet have a shared `__mocks__/lightweight-charts.ts`. If one shows up later, factor this out then.
  - `priceLineSpy` captures calls to `candleSeries.createPriceLine` only; the `lineSeries` mock has its own `createPriceLine` that isn't tracked, so RSI 70/30 calls do **not** pollute the assertion.
  - `titles.sort()` is intentional — implementation order is "supports first then resistances", but order is incidental to the test's intent.

- [ ] **Step 3: Run the new test**

  ```bash
  cd frontend && npx vitest run tests/StockChart.priceLines.test.tsx
  ```

  Expected: 3 PASSED.

  If the test errors with "createChart is not a function" or similar, the `lightweight-charts` mock missed a symbol used at module-import time of `StockChart.tsx`. Add the missing symbol to the `vi.mock` factory return; do **not** simplify the production code to dodge the test.

- [ ] **Step 4: Run the full frontend test suite once to confirm no regression**

  ```bash
  cd frontend && npx vitest run
  ```

  Expected: all green.

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/tests/StockChart.priceLines.test.tsx
  git commit -m "$(cat <<'EOF'
  test(chart): vitest coverage for support/resistance price lines

  Asserts createPriceLine invoked 6× with R1/R2/R3 + S1/S2/S3 titles
  when toggle is on, 0× for S/R when toggle is off, and that all S/R
  lines are removed on unmount.

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 7: Frontend — wire toggle + fetch on the analysis page

**Files:**
- Modify: `frontend/app/(authenticated)/analytics/analysis/page.tsx`

- [ ] **Step 1: Add `Support/Resistance` to `INDICATOR_OPTIONS`**

  Locate the `INDICATOR_OPTIONS` array (≈line 128). Append:

  ```typescript
  { key: "supportResistance", label: "Support/Resistance" },
  ```

  Order: place it after `macd` so it sits at the bottom of the dropdown — visually it's the most distinctive overlay so the bottom slot reads naturally.

- [ ] **Step 2: Extend the indicators fetch to capture S/R arrays**

  Find the `useEffect` (or SWR hook) that calls `${API_URL}/dashboard/chart/indicators?ticker=${q}` (≈line 291). Wherever the parsed response is stored as `chartIndicators`, also pull `support_levels` and `resistance_levels`.

  Concretely:

  - Add two pieces of component state next to `chartIndicators`:
    ```typescript
    const [supportLevels, setSupportLevels] =
      useState<number[]>([]);
    const [resistanceLevels, setResistanceLevels] =
      useState<number[]>([]);
    ```
  - In the response handler, after `setChartIndicators(...)`, add:
    ```typescript
    setSupportLevels(
      Array.isArray(json?.support_levels)
        ? (json.support_levels as number[])
        : [],
    );
    setResistanceLevels(
      Array.isArray(json?.resistance_levels)
        ? (json.resistance_levels as number[])
        : [],
    );
    ```
  - Reset both to `[]` at the start of the fetch (alongside the existing `setChartIndicators([])` reset).

- [ ] **Step 3: Pass props to `<StockChart>`**

  At the chart render site (≈line 526), add the two new props:

  ```tsx
  <StockChart
    ohlcv={chartOhlcv}
    indicators={chartIndicators}
    isDark={isDark}
    height={chartHeight}
    interval={chartInterval}
    visibleIndicators={visibleIndicators}
    onCrosshairMove={handleCrosshair}
    supportLevels={supportLevels}
    resistanceLevels={resistanceLevels}
  />
  ```

- [ ] **Step 4: Type-check + lint**

  ```bash
  cd frontend && npx tsc --noEmit && \
    npx eslint "app/(authenticated)/analytics/analysis/page.tsx"
  ```

  Expected: no errors.

- [ ] **Step 5: Manual smoke**

  Reload `http://localhost:3000/analytics/analysis?ticker=RELIANCE.NS` (or any other liquid ticker that's been through the daily pipeline). Open the Indicators dropdown, toggle `Support/Resistance` on. Verify:
  - 6 dashed horizontal lines appear on the candle pane (3 green below the price, 3 red above).
  - Right-edge tags show `S1 …`, `S2 …`, `S3 …`, `R1 …`, `R2 …`, `R3 …` with the actual level prices.
  - Toggle off → all 6 lines disappear.
  - Switch interval D → W → M → daily lines stay at the same prices.
  - Switch to a different ticker → lines update without leaking old levels.
  - Light/dark theme toggle → colors remain readable.

- [ ] **Step 6: Commit**

  ```bash
  git add "frontend/app/(authenticated)/analytics/analysis/page.tsx"
  git commit -m "$(cat <<'EOF'
  feat(analytics): wire Support/Resistance toggle on analysis page

  Adds the Support/Resistance entry to the Indicators dropdown, fetches
  support_levels + resistance_levels from /chart/indicators alongside
  the existing data points, and passes them through to <StockChart>.
  Default OFF.

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 8: E2E Playwright spec

**Files:**
- Modify: `e2e/tests/frontend/analytics-stock.spec.ts` (extend with one scenario)

- [ ] **Step 1: Inspect the existing spec to match its conventions**

  ```bash
  head -80 e2e/tests/frontend/analytics-stock.spec.ts
  ```

  Note: the file already imports the `AnalyticsPage` POM and uses `toggleIndicator(name)`. The selectors registry already has `stockAnalysisIndicator(name)` — you do **not** need to add a new selector entry.

- [ ] **Step 2: Append the S/R toggle test**

  Add a new test inside the existing `test.describe(...)` block (or create a sibling describe). Use the seeded `superuser` storage state per CLAUDE.md §5.14 — never call `/auth/login` from a spec.

  ```typescript
  test("Support/Resistance toggle renders price-line tags", async ({
    page,
  }) => {
    const analytics = new AnalyticsPage(page);
    await analytics.goto("RELIANCE.NS");
    await analytics
      .stockChartContainer()
      .waitFor({ state: "visible" });

    // Open indicators menu, toggle S/R on.
    await page
      .getByTestId("stock-analysis-indicators-menu")
      .click();
    await analytics.toggleIndicator("supportResistance");

    // Right-edge tags are rendered by TradingView as DOM elements
    // inside the chart's price-axis label layer. Filter the
    // chart container's text content for our tier prefixes.
    const chart = analytics.stockChartContainer();
    await expect
      .poll(async () => {
        const text = (await chart.innerText()) ?? "";
        const matches = text.match(/\b[RS][123]\b/g) ?? [];
        return new Set(matches).size;
      }, { timeout: 5_000 })
      .toBeGreaterThanOrEqual(6);

    // Toggle off → tags gone.
    await analytics.toggleIndicator("supportResistance");
    await expect
      .poll(async () => {
        const text = (await chart.innerText()) ?? "";
        return /\b[RS][123]\b/.test(text);
      }, { timeout: 5_000 })
      .toBe(false);
  });
  ```

  If `chart.innerText()` returns nothing (TradingView renders price labels on a separate canvas+absolute-positioned divs), the spec instead asserts on the count of tag DOM nodes. Fallback assertion:

  ```typescript
  const tags = chart.locator(
    'div:has-text(/^[RS][123]\\s/)',
  );
  await expect(tags).toHaveCount(6, { timeout: 5_000 });
  ```

  Pick whichever locator strategy actually matches what TradingView puts in the DOM after Step 5 of Task 7's manual smoke — DevTools the tag element to confirm. Document the choice with a one-line code comment.

- [ ] **Step 3: Run the new test only**

  ```bash
  cd e2e && \
    npx playwright test \
    tests/frontend/analytics-stock.spec.ts \
    --grep "Support/Resistance toggle" \
    --workers=1 \
    --project=frontend-chromium
  ```

  Expected: 1 passed.

  If the toggle text-locator misses, drop into headed mode to debug:
  ```bash
  cd e2e && \
    npx playwright test \
    tests/frontend/analytics-stock.spec.ts \
    --grep "Support/Resistance toggle" \
    --workers=1 --headed --project=frontend-chromium
  ```

- [ ] **Step 4: Run the whole `analytics-stock.spec.ts` to make sure nothing else broke**

  ```bash
  cd e2e && \
    npx playwright test tests/frontend/analytics-stock.spec.ts \
    --workers=1 --project=frontend-chromium
  ```

  Expected: all tests in this file pass.

- [ ] **Step 5: Commit**

  ```bash
  git add e2e/tests/frontend/analytics-stock.spec.ts
  git commit -m "$(cat <<'EOF'
  test(e2e): cover Support/Resistance toggle on analysis page

  Verifies the Indicators dropdown S/R toggle renders 6 price-line tags
  on (R1/R2/R3 + S1/S2/S3) and clears them on off. Single worker per
  CLAUDE.md §5.14.

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

---

## Task 9: Final sweep + PROGRESS.md + PR

- [ ] **Step 1: Backend lint**

  ```bash
  black backend/ auth/ stocks/ scripts/ && \
    isort backend/ auth/ stocks/ scripts/ --profile black && \
    flake8 backend/ auth/ stocks/ scripts/
  ```

  Expected: no diffs, no flake8 errors.

- [ ] **Step 2: Frontend lint + type-check**

  ```bash
  cd frontend && npx eslint . --fix && npx tsc --noEmit
  ```

  Expected: no errors.

- [ ] **Step 3: Backend pytest suite**

  ```bash
  python -m pytest tests/backend/ -v
  ```

  Expected: same pass/fail counts as before (your 4 new tests added; nothing else regressed). Compare against the baseline from pre-flight.

- [ ] **Step 4: Frontend Vitest suite**

  ```bash
  cd frontend && npx vitest run
  ```

  Expected: all green, 1 new test file present.

- [ ] **Step 5: E2E smoke for the analytics-stock spec only**

  ```bash
  cd e2e && \
    npx playwright test tests/frontend/analytics-stock.spec.ts \
    --workers=1 --project=frontend-chromium
  ```

  Expected: green.

- [ ] **Step 6: Update PROGRESS.md**

  Append a dated session entry to `PROGRESS.md` summarizing: spec link, plan link, what shipped (backend field + route, frontend toggle + chart lines, tests). Match the format of the existing entries near the top of the file.

  ```bash
  git add PROGRESS.md
  git commit -m "$(cat <<'EOF'
  docs: PROGRESS.md entry for stock-chart S/R lines

  Co-Authored-By: Abhay Kumar Singh <asequitytrading@gmail.com>
  EOF
  )"
  ```

- [ ] **Step 7: Push and open PR**

  ```bash
  git push -u origin feature/stock-chart-sr-lines
  gh pr create --base dev --title \
    "feat(chart): support/resistance lines on stock analysis chart" \
    --body "$(cat <<'EOF'
  ## Summary
  - New: 6 horizontal price lines (3 support + 3 resistance) on the candle pane behind a single Indicators-dropdown toggle (default OFF).
  - Backend: `IndicatorsResponse` carries `support_levels` + `resistance_levels` arrays, populated by `_analyse_price_movement` (already produces them). No new endpoint, no schema change.
  - Frontend: extends `IndicatorVisibility`, draws lines via `createPriceLine` (same API as the existing RSI 70/30 references), tier labels `R1`/`R2`/`R3` + `S1`/`S2`/`S3` by proximity to the latest close.

  Spec: `docs/superpowers/specs/2026-05-05-stock-chart-support-resistance-design.md`
  Plan: `docs/superpowers/plans/2026-05-05-stock-chart-support-resistance.md`

  ## Test plan
  - [ ] `python -m pytest tests/backend/test_dashboard_routes.py::TestChartIndicators -v` — 4 new tests + existing all green
  - [ ] `cd frontend && npx vitest run` — new `StockChart.priceLines.test.tsx` green; nothing else regressed
  - [ ] `cd e2e && npx playwright test tests/frontend/analytics-stock.spec.ts --workers=1 --project=frontend-chromium` — all green incl. new S/R toggle case
  - [ ] Manual: open `/analytics/analysis?ticker=RELIANCE.NS`, toggle Support/Resistance — verify 6 tagged lines appear/disappear; switch interval D/W/M — lines unchanged; switch ticker — lines refresh

  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  EOF
  )"
  ```

  Confirm `gh` returns a PR URL. Report it back.

---

## Self-Review (already run inline, captured here for the record)

- **Spec coverage:** Every section of the spec maps to a task —
  - §4 UX → Tasks 4 + 5 + 7
  - §5 Backend (model + handler + cache) → Tasks 1 + 2
  - §6 Frontend → Tasks 4 + 5 + 7
  - §7 Edge cases → covered in tests (Task 3 short-history & empty-OHLCV) and runtime (Task 5 `lastClose === null` guard, Task 7 `Array.isArray` guard)
  - §8 Testing → Tasks 3 + 6 + 8
  - §10 Rollout → Task 2 step 3 (backend restart) + PR description

- **Placeholder scan:** No "TBD" / "TODO" / "implement later" / "appropriate error handling" left in the plan. Every code step has the exact code or exact diff target.

- **Type/method consistency:**
  - `supportResistance` is the toggle key everywhere (`StockChart.types.ts`, `INDICATOR_OPTIONS`, page state setters, e2e selector arg).
  - Field names `support_levels` / `resistance_levels` (snake_case from the JSON wire) mapped to `supportLevels` / `resistanceLevels` (camelCase props) consistently across all tasks.
  - `createPriceLine` / `removePriceLine` symmetric — every line created in Step 2 of Task 5 is freed in Step 3 of Task 5 and asserted free in Task 6's third test.
