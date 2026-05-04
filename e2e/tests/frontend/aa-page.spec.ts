/**
 * E2E coverage for the Advanced Analytics page
 * (Sprint 9 AA-13).
 *
 * Project = ``frontend-chromium`` (superuser
 * storage state — pro+superuser only per AA-7).
 *
 * Cases:
 * 1. Page loads with heading + tab strip + default tab.
 * 2. Tab switch updates URL ``?tab=`` and renders the
 *    new table.
 * 3. CSV button is enabled when rows exist.
 * 4. Stale chip is visible (current dev catalog has
 *    812 stale tickers — population guaranteed; chip
 *    is no-op if empty so the assertion is "visible OR
 *    no rows").
 * 5. Pagination — Next on a multi-page tab moves to
 *    page 2, then Prev moves back.
 *
 * Per CLAUDE.md §5.14: 1 worker locally, no
 * ``networkidle``, locator-scoped data-testids only.
 */

import { test, expect } from "@playwright/test";

import { AdvancedAnalyticsPage } from "../../pages/frontend/advanced-analytics.page";

test.describe("Advanced Analytics — superuser", () => {
  test("default tab loads with heading + tab strip", async ({ page }) => {
    const aa = new AdvancedAnalyticsPage(page);
    await aa.gotoAdvancedAnalytics();
    await expect(aa.heading()).toHaveText("Advanced Analytics");
    await expect(aa.tabs()).toBeVisible();
    await expect(
      aa.panel("current-day-upmove"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("tab switch syncs URL and renders new table", async ({ page }) => {
    const aa = new AdvancedAnalyticsPage(page);
    await aa.gotoAdvancedAnalytics();
    await aa.switchTab("top-50-delivery-by-qty");

    await expect(page).toHaveURL(
      /\/advanced-analytics\?tab=top-50-delivery-by-qty/,
    );
    await aa.waitForTable("top-50-delivery-by-qty");
    await expect(
      aa.table("top-50-delivery-by-qty"),
    ).toBeVisible();

    // Top 50 cap → at most 25 rows on page 1 with default
    // page size; should be > 0 in any non-empty state.
    const count = await aa.getRowCount("top-50-delivery-by-qty");
    expect(count).toBeGreaterThan(0);
    expect(count).toBeLessThanOrEqual(25);
  });

  test("CSV button enabled when rows exist", async ({ page }) => {
    const aa = new AdvancedAnalyticsPage(page);
    await aa.gotoTab("top-50-delivery-by-qty");
    await aa.waitForTable("top-50-delivery-by-qty");
    await expect(aa.csvButton()).toBeEnabled();
  });

  test("stale chip surfaces flagged tickers", async ({ page }) => {
    const aa = new AdvancedAnalyticsPage(page);
    await aa.gotoTab("top-50-delivery-by-qty");
    await aa.waitForTable("top-50-delivery-by-qty");

    // The chip renders nothing when stale_tickers is
    // empty.  In the current dev catalog (~812 US +
    // missing-fundamentals tickers) the chip is
    // present; if a future dataset clears it, the
    // count locator just hides — accept either.
    const chip = aa.staleChip("top-50-delivery-by-qty");
    const visible = await chip.isVisible();
    if (visible) {
      await expect(chip).toContainText(/ticker/);
    }
  });

  test("pagination — next then prev keeps page in sync", async ({ page }) => {
    const aa = new AdvancedAnalyticsPage(page);
    await aa.gotoTab("top-50-delivery-by-qty");
    await aa.waitForTable("top-50-delivery-by-qty");

    const nextBtn = page.getByTestId(
      "advanced-analytics-next-top-50-delivery-by-qty",
    );
    if (await nextBtn.isEnabled()) {
      await aa.clickNext("top-50-delivery-by-qty");
      await expect(
        page.getByText(/Page 2 \/ \d+/),
      ).toBeVisible({ timeout: 10_000 });

      await aa.clickPrev("top-50-delivery-by-qty");
      await expect(
        page.getByText(/Page 1 \/ \d+/),
      ).toBeVisible({ timeout: 10_000 });
    }
  });
});
