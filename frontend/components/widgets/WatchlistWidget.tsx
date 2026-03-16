"use client";

import type { DashboardData } from "@/hooks/useDashboardData";
import type { WatchlistResponse } from "@/lib/types";
import { WidgetSkeleton } from "./WidgetSkeleton";
import { WidgetError } from "./WidgetError";

interface WatchlistWidgetProps {
  data: DashboardData<WatchlistResponse>;
  selectedTicker?: string | null;
  onSelectTicker?: (ticker: string) => void;
}

/** Map ISO currency code to display symbol. */
function currencySymbol(code: string): string {
  const map: Record<string, string> = {
    USD: "$",
    INR: "₹",
    EUR: "€",
    GBP: "£",
    JPY: "¥",
  };
  return map[code?.toUpperCase()] ?? code ?? "$";
}

function Sparkline({
  data,
  positive,
}: {
  data: number[];
  positive: boolean;
}) {
  if (!data.length) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 80;
  const h = 30;
  const points = data
    .map(
      (v, i) =>
        `${(i / (data.length - 1)) * w},${
          h - ((v - min) / range) * h
        }`,
    )
    .join(" ");
  return (
    <svg width={w} height={h} className="shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke={positive ? "#34d399" : "#fb7185"}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function WatchlistWidget({
  data,
  selectedTicker,
  onSelectTicker,
}: WatchlistWidgetProps) {
  if (data.loading) {
    return <WidgetSkeleton className="h-72" />;
  }

  if (data.error) {
    return <WidgetError message={data.error} />;
  }

  const tickers = data.value?.tickers ?? [];

  return (
    <div
      className="
        rounded-xl
        bg-white dark:bg-gray-900
        border border-gray-200 dark:border-gray-800
        overflow-hidden
      "
    >
      {/* Header */}
      <div
        className="
          px-5 py-4
          border-b border-gray-100 dark:border-gray-800
        "
      >
        <h2
          className="
            text-sm font-semibold tracking-wide
            uppercase text-gray-500 dark:text-gray-400
          "
          style={{
            fontFamily: "'DM Sans', sans-serif",
          }}
        >
          Watchlist
        </h2>
      </div>

      {/* Content */}
      {tickers.length === 0 ? (
        <div className="px-5 py-10 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No stocks tracked for this market. Link a
            ticker to get started.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {tickers.map((t, idx) => {
            const positive = t.change >= 0;
            const sym = currencySymbol(t.currency);
            return (
              <div
                key={t.ticker}
                onClick={() =>
                  onSelectTicker?.(t.ticker)
                }
                className={`
                  flex items-center gap-3 px-5 py-3
                  cursor-pointer
                  transition-colors duration-150
                  ${
                    selectedTicker === t.ticker
                      ? "bg-indigo-50/50 dark:bg-indigo-900/20 border-l-2 border-l-indigo-500"
                      : idx % 2 === 1
                        ? "bg-gray-50/50 dark:bg-gray-800/30"
                        : ""
                  }
                  hover:bg-gray-50 dark:hover:bg-gray-800/50
                `}
              >
                {/* Color dot */}
                <span
                  className={`
                    h-2 w-2 shrink-0 rounded-full
                    ${
                      positive
                        ? "bg-emerald-500"
                        : "bg-red-500"
                    }
                  `}
                />

                {/* Ticker + company name */}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                    {t.ticker}
                  </p>
                  {t.company_name && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                      {t.company_name}
                    </p>
                  )}
                </div>

                {/* Current price with currency */}
                <span
                  className="text-sm font-medium text-gray-900 dark:text-white tabular-nums"
                  style={{
                    fontFamily:
                      "'IBM Plex Mono', monospace",
                  }}
                >
                  {sym}
                  {t.current_price.toLocaleString(
                    "en-US",
                    {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    },
                  )}
                </span>

                {/* Change pill */}
                <span
                  className={`
                    inline-flex rounded-full
                    px-2 py-0.5 text-xs font-semibold
                    tabular-nums
                    ${
                      positive
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                        : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                    }
                  `}
                  style={{
                    fontFamily:
                      "'IBM Plex Mono', monospace",
                  }}
                >
                  {positive ? "+" : ""}
                  {t.change_pct.toFixed(2)}%
                </span>

                {/* Sparkline */}
                <Sparkline
                  data={t.sparkline}
                  positive={positive}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
