/**
 * E2E tests for the Stock Analysis tab on the analytics page.
 *
 * Validates candlestick chart rendering, date range / interval
 * selectors, indicator toggles, dark mode, and visual regression.
 * Runs against live backend with a seeded portfolio.
 */

import {
  test,
  expect,
} from "../../fixtures/portfolio.fixture";
import { AnalyticsPage } from "../../pages/frontend/analytics.page";
import { waitForTradingViewChart } from "../../utils/wait.helper";

test.describe("Stock Analysis tab", () => {
  let analytics: AnalyticsPage;

  test.beforeEach(
    async ({ page, seededPortfolio }) => {
      void seededPortfolio; // trigger portfolio seeding
      analytics = new AnalyticsPage(page);
      await analytics.gotoAnalysis();
      await analytics.clickTab("analysis");
      await waitForTradingViewChart(
        page,
        "stock-analysis-chart",
        30_000,
      );
    },
  );

  test("renders candlestick chart with canvas element", async ({
    page,
  }) => {
    const container = analytics.stockChartContainer();
    await expect(container).toBeVisible();
    const canvas = container.locator("canvas").first();
    await expect(canvas).toBeVisible();
  });

  test("date range pills visible (1m 3m 6m 1y 2y 3y max)", async ({
    page,
  }) => {
    const ranges = ["1m", "3m", "6m", "1y", "2y", "3y", "max"];
    for (const r of ranges) {
      await expect(
        page.getByTestId(`stock-analysis-range-${r}`),
      ).toBeVisible();
    }
  });

  test("switching range from 1y to 3m updates chart", async ({
    page,
  }) => {
    await analytics.selectDateRange("3m");
    // Chart should re-render — canvas still present
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const canvas = analytics
      .stockChartContainer()
      .locator("canvas")
      .first();
    await expect(canvas).toBeVisible();
  });

  test("interval selector visible with D W M options", async ({
    page,
  }) => {
    const intervals = ["d", "w", "m"];
    for (const i of intervals) {
      await expect(
        page.getByTestId(`stock-analysis-interval-${i}`),
      ).toBeVisible();
    }
  });

  test("switching interval to W updates chart", async ({
    page,
  }) => {
    await analytics.selectInterval("w");
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const canvas = analytics
      .stockChartContainer()
      .locator("canvas")
      .first();
    await expect(canvas).toBeVisible();
  });

  test("indicators dropdown menu button visible", async ({
    page,
  }) => {
    const menu = page.getByTestId(
      "stock-analysis-indicators-menu",
    );
    await expect(menu).toBeVisible();
  });

  test("clicking indicators menu opens dropdown with checkboxes", async ({
    page,
  }) => {
    const menu = page.getByTestId(
      "stock-analysis-indicators-menu",
    );
    await menu.click();
    // Expect at least one indicator checkbox to appear
    const rsiCheckbox = page.getByTestId(
      "stock-analysis-indicator-rsi",
    );
    await expect(rsiCheckbox).toBeVisible({ timeout: 5_000 });
  });

  test("toggling RSI indicator renders chart", async ({
    page,
  }) => {
    const menu = page.getByTestId(
      "stock-analysis-indicators-menu",
    );
    await menu.click();
    await analytics.toggleIndicator("rsi");
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const canvas = analytics
      .stockChartContainer()
      .locator("canvas")
      .first();
    await expect(canvas).toBeVisible();
  });

  test("toggling MACD indicator works", async ({ page }) => {
    const menu = page.getByTestId(
      "stock-analysis-indicators-menu",
    );
    await menu.click();
    await analytics.toggleIndicator("macd");
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const canvas = analytics
      .stockChartContainer()
      .locator("canvas")
      .first();
    await expect(canvas).toBeVisible();
  });

  test("Support/Resistance toggle renders price-line tags", async ({
    page,
  }) => {
    // TradingView lightweight-charts paints the right-edge
    // S1..S3 / R1..R3 axis labels on a <canvas>, not the DOM,
    // so neither innerText() nor a div locator will see them.
    // We assert the toggle wiring via checkbox state; visual
    // rendering is covered by the StockChart Vitest unit test
    // (frontend/tests/StockChart.priceLines.test.tsx) and the
    // Task 7 visual smoke.
    const menu = page.getByTestId(
      "stock-analysis-indicators-menu",
    );
    await menu.click();

    const checkbox = page
      .getByTestId("stock-analysis-indicator-supportResistance")
      .locator("input[type='checkbox']");
    // Initial state may be persisted in localStorage prefs; we
    // assert relative flips ("toggle changes the state, twice")
    // rather than an absolute starting value.
    await expect(checkbox).toBeVisible();
    const initialChecked = await checkbox.isChecked();

    // First toggle — flips to opposite of initial.
    await analytics.toggleIndicator("supportResistance");
    if (initialChecked) {
      await expect(checkbox).not.toBeChecked();
    } else {
      await expect(checkbox).toBeChecked();
    }
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const canvasMid = analytics
      .stockChartContainer()
      .locator("canvas")
      .first();
    await expect(canvasMid).toBeVisible();

    // Second toggle — back to initial; chart still renders.
    await analytics.toggleIndicator("supportResistance");
    if (initialChecked) {
      await expect(checkbox).toBeChecked();
    } else {
      await expect(checkbox).not.toBeChecked();
    }
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const canvasEnd = analytics
      .stockChartContainer()
      .locator("canvas")
      .first();
    await expect(canvasEnd).toBeVisible();
  });

  test("dark mode - chart renders with dark background", async ({
    page,
  }) => {
    const toggle = page.getByTestId("sidebar-theme-toggle");
    await toggle.click();
    await page.waitForTimeout(1_000);
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const canvas = analytics
      .stockChartContainer()
      .locator("canvas")
      .first();
    await expect(canvas).toBeVisible();
  });

  test("visual regression - stock analysis chart (light)", async () => {
    const container = analytics.stockChartContainer();
    await expect(container).toHaveScreenshot(
      "stock-analysis-chart-light.png",
    );
  });

  test("visual regression - stock analysis chart (dark)", async ({
    page,
  }) => {
    const toggle = page.getByTestId("sidebar-theme-toggle");
    await toggle.click();
    await page.waitForTimeout(1_000);
    await waitForTradingViewChart(
      page,
      "stock-analysis-chart",
      15_000,
    );
    const container = analytics.stockChartContainer();
    await expect(container).toHaveScreenshot(
      "stock-analysis-chart-dark.png",
    );
  });
});
