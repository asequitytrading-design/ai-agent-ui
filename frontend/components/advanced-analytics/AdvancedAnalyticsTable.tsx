"use client";
/**
 * Shared table for the Advanced Analytics 7-tab page
 * (Sprint 9 AA-11). Parameterised by report name + a
 * column catalog (``columnCatalogs.ts``).
 *
 * Mirrors §5.4 tabular-page-pattern:
 * - ``useColumnSelection`` (localStorage-backed) +
 *   ``<ColumnSelector />`` popover for visible cols.
 * - ``visibleCols`` is the single source of truth — table
 *   header/body + ``<DownloadCsvButton />`` consume the
 *   exact same set, never diverge.
 * - Server-side sort + pagination via the SWR hook
 *   (``useAdvancedAnalyticsReport``). Default page size
 *   25; column-header click toggles sort direction +
 *   re-keys SWR.
 * - Stale-ticker chip in the panel-title row (§5.5)
 *   hidden when ``stale_tickers`` is empty.
 *
 * Locked identity column: ``ticker`` (always visible in
 * the column selector).
 */

import { useCallback, useMemo, useState } from "react";

import { ColumnSelector } from "@/components/insights/ColumnSelector";
import {
  DownloadCsvButton,
} from "@/components/common/DownloadCsvButton";
import {
  StaleTickerChip,
  type StaleChipItem,
} from "@/components/common/StaleTickerChip";
import { useAdvancedAnalyticsReport } from "@/hooks/useAdvancedAnalyticsData";
import { downloadCsv, type CsvColumn } from "@/lib/downloadCsv";
import { useColumnSelection } from "@/lib/useColumnSelection";
import {
  ADVANCED_REPORT_LABELS,
  MARKET_FILTER_OPTIONS,
  TICKER_TYPE_FILTER_OPTIONS,
  type AdvancedReportName,
  type AdvancedReportResponse,
  type AdvancedRow,
  type MarketFilter,
  type StaleReason,
  type TickerTypeFilter,
} from "@/lib/types/advancedAnalytics";

import {
  ALL_VALID_KEYS,
  COLUMN_MAP,
  getCatalog,
  type AdvancedColumnKey,
  type AdvancedColumnSpec,
} from "./columnCatalogs";

const DEFAULT_PAGE_SIZE = 25;
const LOCKED_KEYS: string[] = ["ticker"];

const STALE_REASON_LABEL: Record<StaleReason, string> = {
  nan_close: "missing close",
  missing_delivery: "no delivery feed",
  missing_quarterly: "no quarterly data",
  missing_promoter: "no promoter data",
};

interface Props {
  report: AdvancedReportName;
  /** Optional fallbackData passed by the RSC for the
   *  first tab (avoids client-side waterfall on initial
   *  paint). */
  initialData?: AdvancedReportResponse;
}

export function AdvancedAnalyticsTable({ report, initialData }: Props) {
  const { catalog, defaults, storageKey } = getCatalog(report);
  const [selected, setSelected, resetCols] = useColumnSelection(
    storageKey,
    defaults,
    ALL_VALID_KEYS,
  );
  const [page, setPage] = useState(1);
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [market, setMarket] = useState<MarketFilter>("all");
  const [tickerType, setTickerType] =
    useState<TickerTypeFilter>("all");

  // Filters change the result set — reset pagination at the
  // setter site so a stale ?page=4 can't render an empty
  // body. (Avoids the eslint set-state-in-effect cascade.)
  const handleMarketChange = useCallback((next: MarketFilter) => {
    setMarket(next);
    setPage(1);
  }, []);
  const handleTickerTypeChange = useCallback(
    (next: TickerTypeFilter) => {
      setTickerType(next);
      setPage(1);
    },
    [],
  );

  const { value, loading, error } = useAdvancedAnalyticsReport(
    report,
    page,
    DEFAULT_PAGE_SIZE,
    sortKey,
    sortDir,
    market,
    tickerType,
    initialData,
  );

  const visibleCols = useMemo<AdvancedColumnSpec[]>(() => {
    const seen = new Set<string>();
    const order: string[] = [];
    for (const k of LOCKED_KEYS) {
      if (!seen.has(k)) {
        seen.add(k);
        order.push(k);
      }
    }
    for (const k of selected) {
      if (!seen.has(k)) {
        seen.add(k);
        order.push(k);
      }
    }
    return order
      .map((k) => COLUMN_MAP.get(k as AdvancedColumnKey))
      .filter((c): c is AdvancedColumnSpec => c !== undefined);
  }, [selected]);

  const handleSort = useCallback(
    (key: AdvancedColumnKey) => {
      if (sortKey === key) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("desc");
      }
      setPage(1);
    },
    [sortKey],
  );

  const handleCsv = useCallback(() => {
    if (!value || value.rows.length === 0) return;
    const csvCols: CsvColumn<AdvancedRow>[] = visibleCols.map((c) => ({
      key: c.key,
      header: c.label,
      format: (raw) => (c.format ? c.format(raw) : String(raw ?? "")),
    }));
    downloadCsv(value.rows, csvCols, `advanced-analytics-${report}`);
  }, [value, visibleCols, report]);

  const totalPages = value
    ? Math.max(1, Math.ceil(value.total / DEFAULT_PAGE_SIZE))
    : 1;

  const staleItems: StaleChipItem[] = useMemo(() => {
    if (!value) return [];
    return value.stale_tickers.map((s) => ({
      key: s.ticker,
      primary: s.ticker,
      secondary: STALE_REASON_LABEL[s.reason] ?? s.reason,
    }));
  }, [value]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            {ADVANCED_REPORT_LABELS[report]}
          </h2>
          <StaleTickerChip
            items={staleItems}
            summaryLabel={
              staleItems.length === 1
                ? "ticker w/ stale inputs"
                : "tickers w/ stale inputs"
            }
            tooltipTitle="Tickers omitted from / partially in this report:"
            tooltipFooter="Stale rows are skipped from sort & filter; counts auto-clear when upstream data lands."
            testId={`advanced-analytics-stale-${report}`}
          />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={market}
            onChange={(e) =>
              handleMarketChange(e.target.value as MarketFilter)
            }
            data-testid={`advanced-analytics-market-${report}`}
            aria-label="Filter by market"
            className="rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {MARKET_FILTER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={tickerType}
            onChange={(e) =>
              handleTickerTypeChange(e.target.value as TickerTypeFilter)
            }
            data-testid={`advanced-analytics-ticker-type-${report}`}
            aria-label="Filter by ticker type"
            className="rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {TICKER_TYPE_FILTER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ColumnSelector
            catalog={catalog}
            selected={selected}
            onChange={setSelected}
            onReset={resetCols}
            lockedKeys={LOCKED_KEYS}
          />
          <DownloadCsvButton
            onClick={handleCsv}
            disabled={!value || value.rows.length === 0}
          />
        </div>
      </div>

      {error && (
        <div
          className="rounded-md border border-red-200 bg-red-50 dark:border-red-900/50 dark:bg-red-900/20 px-3 py-2 text-sm text-red-700 dark:text-red-400"
          role="alert"
        >
          Failed to load: {error}
        </div>
      )}

      <div
        className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700"
        data-testid={`advanced-analytics-table-${report}`}
      >
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800/50">
            <tr>
              {visibleCols.map((col) => {
                const active = sortKey === col.key;
                const arrow = active ? (sortDir === "desc" ? "▼" : "▲") : "";
                return (
                  <th
                    key={col.key}
                    scope="col"
                    className={`whitespace-nowrap px-3 py-2 text-xs font-medium text-gray-600 dark:text-gray-300 ${
                      col.numeric ? "text-right" : "text-left"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => handleSort(col.key)}
                      data-testid={`advanced-analytics-sort-${col.key}`}
                      className="inline-flex items-center gap-1 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
                    >
                      {col.label}
                      {arrow && (
                        <span className="text-[10px]">{arrow}</span>
                      )}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800 bg-white dark:bg-gray-900">
            {loading && !value ? (
              <tr>
                <td
                  colSpan={visibleCols.length}
                  className="px-3 py-6 text-center text-xs text-gray-500"
                >
                  Loading {ADVANCED_REPORT_LABELS[report]}…
                </td>
              </tr>
            ) : value && value.rows.length > 0 ? (
              value.rows.map((row) => (
                <tr
                  key={row.ticker}
                  className="hover:bg-gray-50 dark:hover:bg-gray-800/50"
                >
                  {visibleCols.map((col) => {
                    const raw = row[col.key];
                    const text = col.format
                      ? col.format(raw)
                      : raw == null
                        ? "—"
                        : String(raw);
                    return (
                      <td
                        key={col.key}
                        className={`whitespace-nowrap px-3 py-2 ${
                          col.numeric
                            ? "text-right tabular-nums text-gray-700 dark:text-gray-200"
                            : "text-gray-700 dark:text-gray-200"
                        }`}
                      >
                        {col.key === "ticker" ? (
                          <span className="font-mono">{text}</span>
                        ) : (
                          text
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))
            ) : (
              <tr>
                <td
                  colSpan={visibleCols.length}
                  className="px-3 py-8 text-center text-xs text-gray-500"
                >
                  No rows match this report&apos;s filter today.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {value && value.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
          <span>
            Showing {(value.page - 1) * value.page_size + 1}–
            {Math.min(
              value.page * value.page_size,
              value.total,
            )}{" "}
            of {value.total.toLocaleString("en-IN")} rows
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-md border border-gray-300 dark:border-gray-700 px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-100 dark:hover:bg-gray-800"
              data-testid={`advanced-analytics-prev-${report}`}
            >
              Prev
            </button>
            <span className="px-2">
              Page {value.page} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() =>
                setPage((p) => Math.min(totalPages, p + 1))
              }
              disabled={page >= totalPages}
              className="rounded-md border border-gray-300 dark:border-gray-700 px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-100 dark:hover:bg-gray-800"
              data-testid={`advanced-analytics-next-${report}`}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
