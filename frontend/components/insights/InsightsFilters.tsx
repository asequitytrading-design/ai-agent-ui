"use client";
/**
 * Shared filter bar for Insights tabs.
 *
 * Provides market, sector, and ticker dropdowns.
 * Each filter is optional — pass the props you need.
 */

interface InsightsFiltersProps {
  /** Market filter. */
  market?: string;
  onMarketChange?: (v: string) => void;
  /** Sector filter (options come from API). */
  sector?: string;
  onSectorChange?: (v: string) => void;
  sectors?: string[];
  /** Ticker filter. */
  ticker?: string;
  onTickerChange?: (v: string) => void;
  tickers?: string[];
  /** Tag filter (nifty50, largecap, etc.). */
  tag?: string;
  onTagChange?: (v: string) => void;
  availableTags?: string[];
  /** RSI filter (screener only). */
  rsiFilter?: string;
  onRsiFilterChange?: (v: string) => void;
}

const TAG_LABELS: Record<string, string> = {
  nifty50: "Nifty 50",
  nifty100: "Nifty 100",
  nifty500: "Nifty 500",
  largecap: "Large Cap",
  midcap: "Mid Cap",
  smallcap: "Small Cap",
  niftymidcap150: "Nifty Midcap 150",
  niftysmallcap250: "Nifty Smallcap 250",
  niftymicrocap250: "Nifty Microcap 250",
};

const selectClass = `
  rounded-lg border border-gray-300
  dark:border-gray-600 bg-white dark:bg-gray-800
  px-2.5 py-1.5 text-sm
  text-gray-700 dark:text-gray-200
  focus:outline-none focus:ring-2
  focus:ring-indigo-500/40
`;

export function InsightsFilters({
  market,
  onMarketChange,
  sector,
  onSectorChange,
  sectors = [],
  ticker,
  onTickerChange,
  tickers = [],
  tag,
  onTagChange,
  availableTags = [],
  rsiFilter,
  onRsiFilterChange,
}: InsightsFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Market */}
      {onMarketChange && (
        <select
          data-testid="insights-market-filter"
          value={market ?? "all"}
          onChange={(e) =>
            onMarketChange(e.target.value)
          }
          className={selectClass}
        >
          <option value="all">All Markets</option>
          <option value="india">India</option>
          <option value="us">US</option>
        </select>
      )}

      {/* Sector */}
      {onSectorChange && sectors.length > 0 && (
        <select
          data-testid="insights-sector-filter"
          value={sector ?? "all"}
          onChange={(e) =>
            onSectorChange(e.target.value)
          }
          className={selectClass}
        >
          <option value="all">All Sectors</option>
          {sectors.map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
      )}

      {/* Ticker */}
      {onTickerChange && tickers.length > 0 && (
        <select
          data-testid="insights-ticker-filter"
          value={ticker ?? "all"}
          onChange={(e) =>
            onTickerChange(e.target.value)
          }
          className={selectClass}
        >
          <option value="all">All Tickers</option>
          {tickers.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      )}

      {/* Tag (nifty50, largecap, etc.) */}
      {onTagChange && availableTags.length > 0 && (
        <select
          data-testid="insights-tag-filter"
          value={tag ?? "all"}
          onChange={(e) =>
            onTagChange(e.target.value)
          }
          className={selectClass}
        >
          <option value="all">All Indices</option>
          {availableTags.map((t) => (
            <option key={t} value={t}>
              {TAG_LABELS[t] || t}
            </option>
          ))}
        </select>
      )}

      {/* RSI (screener only) */}
      {onRsiFilterChange && (
        <select
          data-testid="insights-rsi-filter"
          value={rsiFilter ?? "all"}
          onChange={(e) =>
            onRsiFilterChange(e.target.value)
          }
          className={selectClass}
        >
          <option value="all">All RSI</option>
          <option value="oversold">
            Oversold (&lt;30)
          </option>
          <option value="neutral">
            Neutral (30–70)
          </option>
          <option value="overbought">
            Overbought (&gt;70)
          </option>
        </select>
      )}
    </div>
  );
}
