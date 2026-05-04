"use client";

import { AdvancedAnalyticsTable } from "./AdvancedAnalyticsTable";
import type { AdvancedReportResponse } from "@/lib/types/advancedAnalytics";

export function CurrentDayUpmoveTab({
  initialData,
}: {
  initialData?: AdvancedReportResponse;
}) {
  return (
    <AdvancedAnalyticsTable
      report="current-day-upmove"
      initialData={initialData}
    />
  );
}
