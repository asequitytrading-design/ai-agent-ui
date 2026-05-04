"use client";
/**
 * Reusable amber transparency chip — surfaces a count of
 * tickers with stale / partially-populated inputs (§5.5
 * portfolio-pl-stale-ticker-chip). Hover/click reveals a
 * per-ticker breakdown.
 *
 * Originally lived inside ``components/widgets/PLTrendWidget.tsx``
 * (Sprint 8 ASETPLTFRM-326). Sprint 9 AA-11 generalises it
 * for the Advanced Analytics page (`reason: StaleReason`
 * variant) — both call sites now share this component.
 *
 * Render is a no-op when ``items.length === 0`` so callers
 * can drop the chip in unconditionally.
 */

import { useState } from "react";

export interface StaleChipItem {
  /** Stable React key — usually the ticker symbol. */
  key: string;
  /** Primary label rendered left-aligned (typically the
   *  ticker, displayed monospaced). */
  primary: string;
  /** Secondary detail rendered right-aligned (e.g. a date
   *  + age, or a missing-field reason). */
  secondary: string;
}

interface Props {
  items: StaleChipItem[];
  summaryLabel: string;
  tooltipTitle: string;
  tooltipFooter?: string;
  /** Override the data-testid (defaults to
   *  ``stale-ticker-chip`` so generic E2E selectors work
   *  across the dashboard P&L widget + AA tables). */
  testId?: string;
}

export function StaleTickerChip({
  items,
  summaryLabel,
  tooltipTitle,
  tooltipFooter,
  testId = "stale-ticker-chip",
}: Props) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        data-testid={testId}
        className="inline-flex items-center gap-1 rounded-md bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 px-2 py-0.5 text-xs font-medium border border-amber-200 dark:border-amber-800/50"
      >
        <svg
          className="w-3 h-3"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        {items.length} {summaryLabel}
      </button>
      {open && (
        <div
          role="tooltip"
          data-testid={`${testId}-tooltip`}
          className="absolute right-0 top-full mt-1 z-20 min-w-[240px] rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg p-3 text-xs"
        >
          <p className="text-gray-700 dark:text-gray-200 font-medium mb-2">
            {tooltipTitle}
          </p>
          <ul className="space-y-1 max-h-64 overflow-y-auto">
            {items.map((s) => (
              <li
                key={s.key}
                className="flex items-center justify-between text-gray-600 dark:text-gray-300"
              >
                <span className="font-mono">{s.primary}</span>
                <span className="text-gray-400 dark:text-gray-500">
                  {s.secondary}
                </span>
              </li>
            ))}
          </ul>
          {tooltipFooter && (
            <p className="text-gray-400 dark:text-gray-500 mt-2 text-[11px]">
              {tooltipFooter}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
