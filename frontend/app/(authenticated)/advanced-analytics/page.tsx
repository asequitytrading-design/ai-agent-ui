/**
 * Advanced Analytics route — Server Component wrapper
 * (Sprint 9 AA-10). Mirrors the dashboard / admin
 * RSC pattern (§5.3 cookie-auth-rsc-pattern):
 *
 * 1. Pre-fetch the first-tab payload server-side via
 *    `serverApiOrNull` so SWR's `fallbackData` paints
 *    real numbers on first render — no skeleton step,
 *    no client waterfall.
 * 2. Wrap the client subtree in `<Suspense>` w/ a
 *    static `<h1>` fallback (mirrors the inner heading
 *    + matching `min-h-[600px]` reserve) so the SSR
 *    HTML always carries an LCP candidate even though
 *    `useSearchParams` forces the inner tree client-
 *    only (§5.3 suspense-fallback-null-ssr-hole).
 *
 * Hard 403 for general users is enforced by the
 * `pro_or_superuser` guard on the backend (AA-7) and
 * the `proOrSuperuserOnly` nav gate (AA-9).
 */

import { Suspense } from "react";

import { serverApiOrNull } from "@/lib/serverApi";
import type { AdvancedReportResponse } from "@/lib/types/advancedAnalytics";

import AdvancedAnalyticsClient from "./AdvancedAnalyticsClient";

export const dynamic = "force-dynamic";

export default async function AdvancedAnalyticsPage() {
  let initialData: AdvancedReportResponse | undefined;
  try {
    const data = await serverApiOrNull<AdvancedReportResponse>(
      "/advanced-analytics/current-day-upmove"
      + "?page=1&page_size=25"
      + "&market=india&ticker_type=stock",
    );
    initialData = data ?? undefined;
  } catch {
    // Network / 5xx — degrade to client-side fetch.
    initialData = undefined;
  }

  return (
    <Suspense fallback={<AdvancedAnalyticsFallback />}>
      <AdvancedAnalyticsClient initialData={initialData} />
    </Suspense>
  );
}

function AdvancedAnalyticsFallback() {
  return (
    <div className="space-y-6 p-4 sm:p-6">
      <h1 className="text-2xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
        Advanced Analytics
      </h1>
      <div
        className="min-h-[600px] rounded-lg border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900"
        aria-busy="true"
      />
    </div>
  );
}
