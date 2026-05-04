/**
 * Per-tab column catalogs for the Advanced Analytics
 * 7-tab page (Sprint 9 AA-11).
 *
 * Each catalog drives:
 * - The shared ``<AdvancedAnalyticsTable />`` body.
 * - The ``<ColumnSelector />`` popover (categories
 *   group columns into Identity / Price / Volume /
 *   Delivery / Fundamentals / Promoter / Event).
 * - The ``<DownloadCsvButton />`` (single source of
 *   truth — CSV exports the same ``visibleCols``
 *   as the table per §5.4).
 *
 * Defaults match the source CSV column ordering on
 * disk so users opening the new page see the same
 * shape as the offline reports.
 */

import type { ColumnSpec } from "@/components/insights/ColumnSelector";

import type {
  AdvancedReportName,
  AdvancedRow,
} from "@/lib/types/advancedAnalytics";

export type AdvancedColumnKey = keyof AdvancedRow;

/** ColumnSpec extended with a render formatter +
 *  numeric flag used by the shared table. */
export interface AdvancedColumnSpec extends ColumnSpec {
  key: AdvancedColumnKey;
  /** Format value for the table cell + CSV export. */
  format?: (value: AdvancedRow[AdvancedColumnKey]) => string;
  /** Right-align numeric columns. */
  numeric?: boolean;
}

// ---------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------

const fmt = {
  num: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return "—";
    return n.toLocaleString("en-IN", {
      maximumFractionDigits: 2,
    });
  },
  px2: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return "—";
    return `${n.toFixed(2)}`;
  },
  pct: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return "—";
    return `${(n * 100).toFixed(1)}%`;
  },
  pctRaw: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return "—";
    return `${n.toFixed(2)}%`;
  },
  mult: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return "—";
    return `${n.toFixed(2)}×`;
  },
  intK: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return "—";
    if (Math.abs(n) >= 1e7) return `${(n / 1e7).toFixed(1)} Cr`;
    if (Math.abs(n) >= 1e5) return `${(n / 1e5).toFixed(1)} L`;
    if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)} k`;
    return n.toFixed(0);
  },
  text: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    return String(v);
  },
  date: (v: AdvancedRow[AdvancedColumnKey]): string => {
    if (v === null || v === undefined) return "—";
    const s = String(v);
    return s.length >= 10 ? s.slice(0, 10) : s;
  },
};

// ---------------------------------------------------------------
// Reusable column blocks
// ---------------------------------------------------------------

const IDENTITY: AdvancedColumnSpec[] = [
  { key: "ticker", label: "Ticker", category: "Identity" },
  { key: "company_name", label: "Company", category: "Identity", format: fmt.text },
  { key: "sector", label: "Sector", category: "Identity", format: fmt.text },
  { key: "sub_sector", label: "Sub-sector", category: "Identity", format: fmt.text },
  { key: "pscore", label: "P-Score", category: "Identity", format: fmt.text, numeric: true },
];

const PRICE: AdvancedColumnSpec[] = [
  { key: "today_ltp", label: "LTP", category: "Price", format: fmt.px2, numeric: true },
  { key: "prev_day_ltp", label: "Prev LTP", category: "Price", format: fmt.px2, numeric: true },
  { key: "prev_2_prev_day_ltp", label: "Prev-2 LTP", category: "Price", format: fmt.px2, numeric: true },
  { key: "current_ppc", label: "Current PPC", category: "Price", format: fmt.px2, numeric: true },
  { key: "avg_10d_ppc", label: "Avg 10d PPC", category: "Price", format: fmt.px2, numeric: true },
  { key: "avg_20d_ppc", label: "Avg 20d PPC", category: "Price", format: fmt.px2, numeric: true },
  { key: "week_52_high", label: "52w High", category: "Price", format: fmt.px2, numeric: true },
  { key: "week_52_low", label: "52w Low", category: "Price", format: fmt.px2, numeric: true },
  { key: "away_from_52week_high", label: "↓ from 52w H", category: "Price", format: fmt.pctRaw, numeric: true },
];

const VOLUME: AdvancedColumnSpec[] = [
  { key: "today_vol", label: "Today Vol", category: "Volume", format: fmt.intK, numeric: true },
  { key: "prev_day_vol", label: "Prev Vol", category: "Volume", format: fmt.intK, numeric: true },
  { key: "avg_10d_vol", label: "Avg 10d Vol", category: "Volume", format: fmt.intK, numeric: true },
  { key: "avg_20d_vol", label: "Avg 20d Vol", category: "Volume", format: fmt.intK, numeric: true },
  { key: "today_x_vol", label: "Today × Vol", category: "Volume", format: fmt.mult, numeric: true },
  { key: "prev_day_x_vol", label: "Prev × Vol", category: "Volume", format: fmt.mult, numeric: true },
  { key: "x_vol_10d", label: "× Vol 10d", category: "Volume", format: fmt.mult, numeric: true },
  { key: "x_vol_20d", label: "× Vol 20d", category: "Volume", format: fmt.mult, numeric: true },
];

const DELIVERY: AdvancedColumnSpec[] = [
  { key: "today_dv", label: "Today DV", category: "Delivery", format: fmt.intK, numeric: true },
  { key: "prev_day_dv", label: "Prev DV", category: "Delivery", format: fmt.intK, numeric: true },
  { key: "avg_10d_dv", label: "Avg 10d DV", category: "Delivery", format: fmt.intK, numeric: true },
  { key: "avg_20d_dv", label: "Avg 20d DV", category: "Delivery", format: fmt.intK, numeric: true },
  { key: "today_dpc", label: "Today DPC", category: "Delivery", format: fmt.pctRaw, numeric: true },
  { key: "prev_day_dpc", label: "Prev DPC", category: "Delivery", format: fmt.pctRaw, numeric: true },
  { key: "avg_10d_dpc", label: "Avg 10d DPC", category: "Delivery", format: fmt.pctRaw, numeric: true },
  { key: "avg_20d_dpc", label: "Avg 20d DPC", category: "Delivery", format: fmt.pctRaw, numeric: true },
  { key: "today_x_dv", label: "Today × DV", category: "Delivery", format: fmt.mult, numeric: true },
  { key: "prev_day_x_dv", label: "Prev × DV", category: "Delivery", format: fmt.mult, numeric: true },
  { key: "x_dv_10d", label: "× DV 10d", category: "Delivery", format: fmt.mult, numeric: true },
  { key: "x_dv_20d", label: "× DV 20d", category: "Delivery", format: fmt.mult, numeric: true },
  { key: "current_dpc", label: "Current DPC", category: "Delivery", format: fmt.pctRaw, numeric: true },
];

const NOTIONAL: AdvancedColumnSpec[] = [
  { key: "today_not", label: "Today Notional", category: "Notional", format: fmt.intK, numeric: true },
  { key: "avg_10d_not", label: "Avg 10d Notional", category: "Notional", format: fmt.intK, numeric: true },
  { key: "avg_20d_not", label: "Avg 20d Notional", category: "Notional", format: fmt.intK, numeric: true },
];

const TECHNICAL: AdvancedColumnSpec[] = [
  { key: "rsi", label: "RSI 14", category: "Technical", format: fmt.px2, numeric: true },
  { key: "avg_emv_score", label: "EMV-14", category: "Technical", format: fmt.px2, numeric: true },
  { key: "avg_14d_emv", label: "Avg 14d EMV", category: "Technical", format: fmt.px2, numeric: true },
  { key: "sma_50", label: "SMA 50", category: "Technical", format: fmt.px2, numeric: true },
  { key: "sma_200", label: "SMA 200", category: "Technical", format: fmt.px2, numeric: true },
];

const FUNDAMENTALS: AdvancedColumnSpec[] = [
  { key: "debt_to_eq", label: "Debt / Eq", category: "Fundamentals", format: fmt.px2, numeric: true },
  { key: "yoy_qtr_prft", label: "YoY Qtr Profit", category: "Fundamentals", format: fmt.pct, numeric: true },
  { key: "yoy_qtr_sales", label: "YoY Qtr Sales", category: "Fundamentals", format: fmt.pct, numeric: true },
  { key: "sales_growth_3yrs", label: "Sales 3y CAGR", category: "Fundamentals", format: fmt.pct, numeric: true },
  { key: "prft_growth_3yrs", label: "Profit 3y CAGR", category: "Fundamentals", format: fmt.pct, numeric: true },
  { key: "sales_growth_5yrs", label: "Sales 5y CAGR", category: "Fundamentals", format: fmt.pct, numeric: true },
  { key: "prft_growth_5yrs", label: "Profit 5y CAGR", category: "Fundamentals", format: fmt.pct, numeric: true },
  { key: "roce", label: "ROCE", category: "Fundamentals", format: fmt.pct, numeric: true },
];

const PROMOTER: AdvancedColumnSpec[] = [
  { key: "prom_hld", label: "Promoter %", category: "Promoter", format: fmt.pctRaw, numeric: true },
  { key: "pledged", label: "Pledged %", category: "Promoter", format: fmt.pctRaw, numeric: true },
  { key: "chng_in_prom_hld", label: "Δ Promoter %", category: "Promoter", format: fmt.pctRaw, numeric: true },
];

const EVENT: AdvancedColumnSpec[] = [
  { key: "event", label: "Latest Event", category: "Event", format: fmt.text },
  { key: "event_date", label: "Event Date", category: "Event", format: fmt.date },
];

const ALL_COLUMNS: AdvancedColumnSpec[] = [
  ...IDENTITY,
  ...PRICE,
  ...VOLUME,
  ...DELIVERY,
  ...NOTIONAL,
  ...TECHNICAL,
  ...FUNDAMENTALS,
  ...PROMOTER,
  ...EVENT,
];

// ---------------------------------------------------------------
// Per-tab catalogs
// ---------------------------------------------------------------

interface CatalogConfig {
  defaults: AdvancedColumnKey[];
  storageKey: string;
}

const CATALOG_CONFIG: Record<AdvancedReportName, CatalogConfig> = {
  "current-day-upmove": {
    storageKey: "aa-tab-current-day-upmove-cols",
    defaults: [
      "ticker", "sector", "pscore",
      "today_ltp", "current_ppc", "avg_20d_ppc",
      "today_x_vol", "x_vol_20d",
      "today_dpc", "avg_20d_dpc",
      "avg_emv_score", "rsi",
      "week_52_high", "away_from_52week_high",
    ],
  },
  "previous-day-breakout": {
    storageKey: "aa-tab-previous-day-breakout-cols",
    defaults: [
      "ticker", "sector", "pscore",
      "today_ltp", "prev_day_ltp",
      "today_x_vol", "prev_day_x_vol",
      "today_dpc", "prev_day_dpc",
      "x_dv_20d",
    ],
  },
  "mom-volume-delivery": {
    storageKey: "aa-tab-mom-volume-delivery-cols",
    defaults: [
      "ticker", "sector",
      "today_ltp", "avg_20d_ppc",
      "today_vol", "avg_20d_vol", "x_vol_20d",
      "today_dv", "avg_20d_dv", "x_dv_20d",
      "today_dpc", "avg_20d_dpc",
    ],
  },
  "wow-volume-delivery": {
    storageKey: "aa-tab-wow-volume-delivery-cols",
    defaults: [
      "ticker", "sector",
      "today_ltp", "avg_10d_ppc",
      "today_vol", "avg_10d_vol", "x_vol_10d",
      "today_dv", "avg_10d_dv", "x_dv_10d",
      "today_dpc", "avg_10d_dpc",
    ],
  },
  "two-day-scan": {
    storageKey: "aa-tab-two-day-scan-cols",
    defaults: [
      "ticker", "sector", "pscore",
      "today_ltp", "prev_day_ltp",
      "today_x_vol", "prev_day_x_vol",
      "today_dpc", "prev_day_dpc",
    ],
  },
  "three-day-scan": {
    storageKey: "aa-tab-three-day-scan-cols",
    defaults: [
      "ticker", "sector", "pscore",
      "today_ltp", "prev_day_ltp", "prev_2_prev_day_ltp",
      "today_x_vol", "prev_day_x_vol",
      "today_dpc", "prev_day_dpc",
    ],
  },
  "top-50-delivery-by-qty": {
    storageKey: "aa-tab-top-50-delivery-by-qty-cols",
    defaults: [
      "ticker", "sector", "pscore",
      "today_ltp", "today_vol", "today_dv",
      "today_dpc", "x_dv_20d",
      "debt_to_eq", "roce",
      "prom_hld", "pledged",
      "event", "event_date",
    ],
  },
};

export function getCatalog(report: AdvancedReportName): {
  catalog: AdvancedColumnSpec[];
  defaults: AdvancedColumnKey[];
  storageKey: string;
} {
  const cfg = CATALOG_CONFIG[report];
  return {
    catalog: ALL_COLUMNS,
    defaults: cfg.defaults,
    storageKey: cfg.storageKey,
  };
}

/** All column keys (used by ``useColumnSelection`` for
 *  validity filtering when reading persisted state). */
export const ALL_VALID_KEYS: string[] = ALL_COLUMNS.map((c) => c.key);

/** Column lookup keyed by field name. */
export const COLUMN_MAP: Map<AdvancedColumnKey, AdvancedColumnSpec> =
  new Map(ALL_COLUMNS.map((c) => [c.key, c]));
