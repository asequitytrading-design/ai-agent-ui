/**
 * In-app reference for every Advanced Analytics column —
 * powers the `<HelpTab />` (8th tab on the AA page).
 *
 * Definitions are derived from the column compute paths in
 * ``backend/advanced_analytics_routes.py`` (`_build_row` and
 * helpers) plus standard NSE bhavcopy / fundamentals
 * conventions. Edit here if a column's compute changes —
 * this file is the single source of truth for user-facing
 * docs of the AA reports.
 *
 * Field shape:
 *   - ``description`` — plain-English, one-sentence "what".
 *   - ``formula`` — computational definition (monospace).
 *   - ``tradingTakeaway`` — one-line "so what" for trade decisions.
 */

import type { AdvancedColumnKey } from "./columnCatalogs";

export type ColumnCategory =
  | "Identity"
  | "Price"
  | "Volume"
  | "Delivery"
  | "Notional"
  | "Technical"
  | "Fundamentals"
  | "Promoter"
  | "Event";

export interface ColumnDoc {
  key: AdvancedColumnKey;
  label: string;
  category: ColumnCategory;
  description: string;
  formula: string;
  tradingTakeaway: string;
}

/** Quick read-me for each grouping that frames the columns
 *  underneath. Keeps the tab scannable. */
export const CATEGORY_BLURBS: Record<ColumnCategory, string> = {
  Identity:
    "Symbol, name, sector, and overall quality grade — used to scope filters and CSV exports.",
  Price:
    "Last Traded Price (LTP) snapshots and short-window percentage moves. Use these to gauge today's move relative to the recent baseline.",
  Volume:
    "Raw share-count traded plus multipliers vs the rolling baseline. Volume confirms (or denies) a price move.",
  Delivery:
    "Of the total volume, how many shares were marked for delivery (taken into demat) instead of intraday-squared. High delivery % = high conviction.",
  Notional:
    "Total INR turnover (price × volume). Useful for sizing — a 10× volume spike on a small-cap may still be tiny in rupee terms.",
  Technical:
    "Trend & momentum indicators — RSI, EMV, and SMAs. Direction signals, not price targets.",
  Fundamentals:
    "Balance-sheet and earnings quality. Use to filter high-conviction setups from the technical scans.",
  Promoter:
    "Insider holding patterns. Big swings here often lead price moves by quarters.",
  Event:
    "Latest corporate-action timestamp (board meeting, dividend, results). Watch for catalysts.",
};

/** Glossary inline at the top of the Help tab. */
export const GLOSSARY: { term: string; definition: string }[] = [
  {
    term: "LTP",
    definition: "Last Traded Price — the close for the latest session.",
  },
  {
    term: "PPC",
    definition:
      "Price Percent Change — (today's close − previous close) / previous close × 100.",
  },
  {
    term: "DV",
    definition:
      "Delivery Value — shares marked for delivery (not intraday) × LTP, in INR.",
  },
  {
    term: "DPC",
    definition:
      "Delivery Percent of Volume — delivered shares / total traded shares × 100. Higher = more conviction.",
  },
  {
    term: "× Vol / × DV",
    definition:
      "Multiplier vs the rolling baseline (e.g. today_x_vol = today_vol / avg_20d_vol). 1× = normal, 2× = double, etc.",
  },
  {
    term: "Notional",
    definition:
      "Total turnover in INR (vol × price). Different from DV — notional includes intraday churn.",
  },
  {
    term: "EMV-14",
    definition:
      "Ease of Movement (14-day). Positive = price moving up on lighter volume relative to range; negative = downtrend.",
  },
  {
    term: "P-Score",
    definition:
      "Piotroski F-Score (0-9). Composite balance-sheet quality grade. ≥ 7 is strong.",
  },
];

// ---------------------------------------------------------------
// Per-column docs
// ---------------------------------------------------------------

export const COLUMN_DOCS: ColumnDoc[] = [
  // ── Identity ──────────────────────────────────────────────
  {
    key: "ticker",
    label: "Ticker",
    category: "Identity",
    description:
      "Yahoo-Finance-style symbol with exchange suffix (.NS for NSE, .BO for BSE).",
    formula: "<symbol>.<NS|BO>",
    tradingTakeaway:
      "Use the search box to jump straight to a ticker without paging.",
  },
  {
    key: "company_name",
    label: "Company",
    category: "Identity",
    description: "Registered company name from Yahoo Finance company info.",
    formula: "company_info.company_name",
    tradingTakeaway:
      "Helpful in cross-referencing news / filings outside the platform.",
  },
  {
    key: "sector",
    label: "Sector",
    category: "Identity",
    description: "Top-level GICS sector (e.g. Financial Services, Technology).",
    formula: "company_info.sector",
    tradingTakeaway:
      "Run sector-wide scans to spot rotation (e.g. all Financial Services with high today_x_vol).",
  },
  {
    key: "sub_sector",
    label: "Sub-sector",
    category: "Identity",
    description: "Industry / sub-sector classification (more granular than sector).",
    formula: "company_info.industry",
    tradingTakeaway: "Pinpoints peers within a sector for relative-strength comparison.",
  },
  {
    key: "pscore",
    label: "P-Score",
    category: "Identity",
    description:
      "Piotroski F-Score, 0-9 composite of profitability, leverage / liquidity, and operating efficiency signals.",
    formula:
      "Σ of 9 binary tests on quarterly_results (ROA>0, ΔROA>0, OpCF>0, OpCF>NetIncome, ΔLeverage<0, ΔCurrentRatio>0, no new shares issued, ΔGrossMargin>0, ΔAssetTurnover>0)",
    tradingTakeaway:
      "Filter for ≥ 7 to skew toward fundamentally healthy names; combine with momentum scans to find quality breakouts.",
  },

  // ── Price ─────────────────────────────────────────────────
  {
    key: "today_ltp",
    label: "LTP",
    category: "Price",
    description: "Today's session close price.",
    formula: "ohlcv.close[date == today]",
    tradingTakeaway: "Anchor for all percentage and multiplier calculations.",
  },
  {
    key: "prev_day_ltp",
    label: "Prev LTP",
    category: "Price",
    description: "Previous trading day's close.",
    formula: "ohlcv.close[date == today - 1 trading day]",
    tradingTakeaway: "Reference for today's gap and percent change.",
  },
  {
    key: "prev_2_prev_day_ltp",
    label: "Prev-2 LTP",
    category: "Price",
    description: "Close two trading days before today (T-2).",
    formula: "ohlcv.close[date == today - 2 trading days]",
    tradingTakeaway:
      "Enables 3-day momentum / continuation reads in the Three-Day Scan tab.",
  },
  {
    key: "current_ppc",
    label: "Current PPC",
    category: "Price",
    description: "Today's price percent change vs previous close.",
    formula: "(today_ltp − prev_day_ltp) / prev_day_ltp × 100",
    tradingTakeaway:
      "Combine with today_x_vol > 1 + today_dpc > avg_20d_dpc to confirm a real breakout vs noise.",
  },
  {
    key: "avg_10d_ppc",
    label: "Avg 10d PPC",
    category: "Price",
    description: "Mean price percent change over the last 10 trading sessions.",
    formula: "mean(daily_ppc over last 10 sessions)",
    tradingTakeaway:
      "Gauges short-term drift. current_ppc > avg_10d_ppc suggests the trend is accelerating.",
  },
  {
    key: "avg_20d_ppc",
    label: "Avg 20d PPC",
    category: "Price",
    description: "Mean price percent change over the last 20 trading sessions.",
    formula: "mean(daily_ppc over last 20 sessions)",
    tradingTakeaway:
      "Smoother baseline. A 20d positive average with rising delivery suggests sustained accumulation.",
  },
  {
    key: "week_52_high",
    label: "52w High",
    category: "Price",
    description: "Highest close in the trailing 252 trading sessions (~52 weeks).",
    formula: "max(ohlcv.close over last 252 sessions)",
    tradingTakeaway:
      "Breakouts above 52w high on heavy volume are classic momentum entries.",
  },
  {
    key: "week_52_low",
    label: "52w Low",
    category: "Price",
    description: "Lowest close in the trailing 252 trading sessions.",
    formula: "min(ohlcv.close over last 252 sessions)",
    tradingTakeaway:
      "Names trading near 52w low with positive prft_3y_cagr can be value-reset candidates.",
  },
  {
    key: "away_from_52week_high",
    label: "↓ from 52w High",
    category: "Price",
    description:
      "Percent below today's price relative to the 52-week high (typically negative).",
    formula: "(today_ltp − week_52_high) / week_52_high × 100",
    tradingTakeaway:
      "0% to −5% = momentum sweet spot; below −30% = potential reversal/value zone (pair with low RSI).",
  },

  // ── Volume ────────────────────────────────────────────────
  {
    key: "today_vol",
    label: "Today Vol",
    category: "Volume",
    description: "Total shares traded in today's session.",
    formula: "sum(ohlcv.volume[date == today])",
    tradingTakeaway: "Raw activity. Compare against avg_20d_vol via today_x_vol.",
  },
  {
    key: "prev_day_vol",
    label: "Prev Vol",
    category: "Volume",
    description: "Total shares traded the previous session.",
    formula: "sum(ohlcv.volume[date == today − 1])",
    tradingTakeaway: "Used in two-day continuation scans.",
  },
  {
    key: "avg_10d_vol",
    label: "Avg 10d Vol",
    category: "Volume",
    description: "Mean daily volume over the last 10 trading sessions.",
    formula: "mean(ohlcv.volume over last 10 sessions)",
    tradingTakeaway: "Short-window baseline — sensitive to recent regime change.",
  },
  {
    key: "avg_20d_vol",
    label: "Avg 20d Vol",
    category: "Volume",
    description: "Mean daily volume over the last 20 trading sessions.",
    formula: "mean(ohlcv.volume over last 20 sessions)",
    tradingTakeaway:
      "Standard 'normal' baseline. Used as the denominator for today_x_vol.",
  },
  {
    key: "today_x_vol",
    label: "Today × Vol",
    category: "Volume",
    description: "Today's volume as a multiple of the 20-day average.",
    formula: "today_vol / avg_20d_vol",
    tradingTakeaway:
      ">2× signals unusual activity. Direction (up/down) is given by current_ppc; conviction by today_dpc.",
  },
  {
    key: "prev_day_x_vol",
    label: "Prev × Vol",
    category: "Volume",
    description: "Yesterday's volume as a multiple of the 20-day average.",
    formula: "prev_day_vol / avg_20d_vol",
    tradingTakeaway:
      "Two consecutive days >1× often mark the start of a multi-day move (Two-Day Scan tab).",
  },
  {
    key: "x_vol_10d",
    label: "× Vol 10d",
    category: "Volume",
    description:
      "Today's volume as a multiple of the 10-day average (faster-reacting baseline).",
    formula: "today_vol / avg_10d_vol",
    tradingTakeaway:
      "WoW Volume / Delivery tab uses this — catches volume regime shifts that the 20d baseline smooths over.",
  },
  {
    key: "x_vol_20d",
    label: "× Vol 20d",
    category: "Volume",
    description: "Same as today_x_vol — included for explicit MoM comparisons.",
    formula: "today_vol / avg_20d_vol",
    tradingTakeaway:
      "MoM Volume / Delivery tab uses this — slower-reacting confirmation of a regime change.",
  },

  // ── Delivery ──────────────────────────────────────────────
  {
    key: "today_dv",
    label: "Today DV",
    category: "Delivery",
    description: "Delivery value (in INR) for today — shares marked for delivery × LTP.",
    formula: "nse_delivery.delivered_qty[today] × today_ltp",
    tradingTakeaway:
      "Raw conviction-rupees. Compare across tickers via × DV multiples; large absolute DV doesn't help in isolation.",
  },
  {
    key: "prev_day_dv",
    label: "Prev DV",
    category: "Delivery",
    description: "Previous day's delivery value (INR).",
    formula: "nse_delivery.delivered_qty[T-1] × prev_day_ltp",
    tradingTakeaway: "Two-day persistent DV growth is stronger than a one-day spike.",
  },
  {
    key: "avg_10d_dv",
    label: "Avg 10d DV",
    category: "Delivery",
    description: "Mean delivery value over the last 10 trading sessions.",
    formula: "mean(daily_dv over last 10 sessions)",
    tradingTakeaway: "Short-window baseline for the WoW Delivery tab.",
  },
  {
    key: "avg_20d_dv",
    label: "Avg 20d DV",
    category: "Delivery",
    description: "Mean delivery value over the last 20 trading sessions.",
    formula: "mean(daily_dv over last 20 sessions)",
    tradingTakeaway: "Standard baseline. Denominator for today_x_dv and x_dv_20d.",
  },
  {
    key: "today_dpc",
    label: "Today DPC",
    category: "Delivery",
    description:
      "Today's delivery percent — share of total traded volume that was taken into demat instead of intraday-squared.",
    formula: "delivered_qty[today] / today_vol × 100",
    tradingTakeaway:
      ">50% = high conviction (likely positional); <20% = mostly intraday churn. Combine with current_ppc to read direction.",
  },
  {
    key: "prev_day_dpc",
    label: "Prev DPC",
    category: "Delivery",
    description: "Previous day's delivery percent.",
    formula: "delivered_qty[T-1] / prev_day_vol × 100",
    tradingTakeaway: "Two-day rising DPC = sustained positional interest.",
  },
  {
    key: "avg_10d_dpc",
    label: "Avg 10d DPC",
    category: "Delivery",
    description: "Mean delivery percent over the last 10 sessions.",
    formula: "mean(daily_dpc over last 10 sessions)",
    tradingTakeaway:
      "Short baseline. today_dpc > avg_10d_dpc + today_x_vol > 1 = breakout candidate.",
  },
  {
    key: "avg_20d_dpc",
    label: "Avg 20d DPC",
    category: "Delivery",
    description: "Mean delivery percent over the last 20 sessions.",
    formula: "mean(daily_dpc over last 20 sessions)",
    tradingTakeaway:
      "Used by the Current Day Upmove tab as the conviction-reset baseline.",
  },
  {
    key: "today_x_dv",
    label: "Today × DV",
    category: "Delivery",
    description: "Today's delivery value as a multiple of the 20-day average.",
    formula: "today_dv / avg_20d_dv",
    tradingTakeaway:
      ">3× with positive current_ppc = institution-grade accumulation signal.",
  },
  {
    key: "prev_day_x_dv",
    label: "Prev × DV",
    category: "Delivery",
    description: "Previous day's DV as a multiple of the 20-day average.",
    formula: "prev_day_dv / avg_20d_dv",
    tradingTakeaway: "Catches the lead day of a multi-day delivery wave.",
  },
  {
    key: "x_dv_10d",
    label: "× DV 10d",
    category: "Delivery",
    description: "Today's DV as a multiple of the 10-day average.",
    formula: "today_dv / avg_10d_dv",
    tradingTakeaway:
      "WoW Delivery tab default. Catches week-on-week regime shifts.",
  },
  {
    key: "x_dv_20d",
    label: "× DV 20d",
    category: "Delivery",
    description: "Same as today_x_dv — explicit MoM framing.",
    formula: "today_dv / avg_20d_dv",
    tradingTakeaway:
      "MoM Delivery tab default. Slower but more meaningful when sustained.",
  },
  {
    key: "current_dpc",
    label: "Current DPC",
    category: "Delivery",
    description: "Alias for today_dpc — included as a stable column for filter clarity.",
    formula: "delivered_qty[today] / today_vol × 100",
    tradingTakeaway:
      "Used in the Current Day Upmove filter (current_dpc > avg_20d_dpc).",
  },

  // ── Notional ──────────────────────────────────────────────
  {
    key: "today_not",
    label: "Today Notional",
    category: "Notional",
    description: "Total INR turnover today — includes intraday churn (unlike DV).",
    formula: "today_vol × today_ltp",
    tradingTakeaway:
      "Sanity-check liquidity. A 10× volume spike on a stock with ₹1 Cr notional is still untradeable.",
  },
  {
    key: "avg_10d_not",
    label: "Avg 10d Notional",
    category: "Notional",
    description: "Mean daily notional over the last 10 trading sessions.",
    formula: "mean(daily_notional over last 10 sessions)",
    tradingTakeaway: "Short liquidity baseline.",
  },
  {
    key: "avg_20d_not",
    label: "Avg 20d Notional",
    category: "Notional",
    description: "Mean daily notional over the last 20 trading sessions.",
    formula: "mean(daily_notional over last 20 sessions)",
    tradingTakeaway:
      "Use as your minimum-liquidity gate (e.g. avg_20d_not > ₹50 Cr for mid-cap setups).",
  },

  // ── Technical ─────────────────────────────────────────────
  {
    key: "rsi",
    label: "RSI 14",
    category: "Technical",
    description:
      "Wilder's Relative Strength Index over 14 sessions, scaled 0-100.",
    formula: "100 − (100 / (1 + (avg_gain_14 / avg_loss_14)))",
    tradingTakeaway:
      "<30 oversold (potential reversal); >70 overbought (caution). 50 is neutral.",
  },
  {
    key: "avg_emv_score",
    label: "EMV-14",
    category: "Technical",
    description:
      "Ease of Movement (14-day average). Combines price move + range vs volume.",
    formula:
      "EMV_t = ((H_t+L_t)/2 − (H_{t-1}+L_{t-1})/2) / (V_t / (H_t − L_t)); avg over 14 sessions",
    tradingTakeaway:
      "Positive = up-trend on light volume (efficient); negative = down-trend. Sustained sign change leads price moves.",
  },
  {
    key: "avg_14d_emv",
    label: "Avg 14d EMV",
    category: "Technical",
    description:
      "14-day mean of the daily EMV score (smoothed view of avg_emv_score).",
    formula: "mean(EMV_t over last 14 sessions)",
    tradingTakeaway:
      "Cross from negative to positive often precedes a reversal in trend by 2-5 sessions.",
  },
  {
    key: "sma_50",
    label: "SMA 50",
    category: "Technical",
    description: "50-session simple moving average of close.",
    formula: "mean(ohlcv.close over last 50 sessions)",
    tradingTakeaway:
      "Short-trend reference. Price > SMA 50 = bullish bias; reverse for bearish.",
  },
  {
    key: "sma_200",
    label: "SMA 200",
    category: "Technical",
    description: "200-session simple moving average of close — long-trend benchmark.",
    formula: "mean(ohlcv.close over last 200 sessions)",
    tradingTakeaway:
      "SMA 50 crossing above SMA 200 = 'golden cross' (trend buy); below = 'death cross' (trend sell).",
  },

  // ── Fundamentals ──────────────────────────────────────────
  {
    key: "debt_to_eq",
    label: "Debt / Eq",
    category: "Fundamentals",
    description:
      "Total debt divided by shareholders' equity (latest reported balance sheet).",
    formula: "total_debt / total_equity",
    tradingTakeaway:
      "<0.5 = conservative; 0.5-1.5 = moderate leverage; >2 = high risk in a downturn.",
  },
  {
    key: "yoy_qtr_prft",
    label: "YoY Qtr Profit",
    category: "Fundamentals",
    description: "Latest quarter net profit growth vs the same quarter a year ago.",
    formula:
      "(latest_qtr.net_profit − same_qtr_prev_year.net_profit) / |same_qtr_prev_year.net_profit| × 100",
    tradingTakeaway: "Sustained positive YoY profit growth = compounding business.",
  },
  {
    key: "yoy_qtr_sales",
    label: "YoY Qtr Sales",
    category: "Fundamentals",
    description: "Latest quarter revenue growth vs the same quarter a year ago.",
    formula:
      "(latest_qtr.sales − same_qtr_prev_year.sales) / same_qtr_prev_year.sales × 100",
    tradingTakeaway:
      "Combine with YoY profit — sales growth without profit growth flags margin compression.",
  },
  {
    key: "sales_growth_3yrs",
    label: "Sales 3y CAGR",
    category: "Fundamentals",
    description: "Compound annual growth rate of sales over the last 3 years.",
    formula:
      "(latest_qtr.sales / qtr_12_back.sales)^(1/3) − 1; needs ≥ 12 quarters of history",
    tradingTakeaway:
      ">15% = high-growth bucket. Sparse for newer listings (fills as quarterly history accumulates).",
  },
  {
    key: "prft_growth_3yrs",
    label: "Profit 3y CAGR",
    category: "Fundamentals",
    description: "Compound annual growth rate of net profit over the last 3 years.",
    formula:
      "(latest_qtr.net_profit / qtr_12_back.net_profit)^(1/3) − 1",
    tradingTakeaway:
      ">15% with prft_5y_cagr also positive = durable compounder.",
  },
  {
    key: "sales_growth_5yrs",
    label: "Sales 5y CAGR",
    category: "Fundamentals",
    description: "5-year compound annual growth rate of sales.",
    formula: "(latest_qtr.sales / qtr_20_back.sales)^(1/5) − 1; needs ≥ 20 quarters",
    tradingTakeaway:
      "Longer horizon than the 3y figure. Sparse today; populates over quarters.",
  },
  {
    key: "prft_growth_5yrs",
    label: "Profit 5y CAGR",
    category: "Fundamentals",
    description: "5-year compound annual growth rate of net profit.",
    formula: "(latest_qtr.net_profit / qtr_20_back.net_profit)^(1/5) − 1",
    tradingTakeaway: "Best signal of long-term earnings durability when populated.",
  },
  {
    key: "roce",
    label: "ROCE",
    category: "Fundamentals",
    description:
      "Return on Capital Employed — operating efficiency of the business.",
    formula: "EBIT / (total_assets − current_liabilities) × 100",
    tradingTakeaway:
      ">20% sustained = capital-efficient business. Pair with debt_to_eq < 1 for quality bucket.",
  },

  // ── Promoter ──────────────────────────────────────────────
  {
    key: "prom_hld",
    label: "Promoter %",
    category: "Promoter",
    description:
      "Percentage of total shares outstanding held by promoters (latest BSE filing).",
    formula: "promoter_holding_shares / total_shares × 100",
    tradingTakeaway:
      "Stable >50% promoter holding = strong control. Sub-25% raises governance / takeover questions.",
  },
  {
    key: "pledged",
    label: "Pledged %",
    category: "Promoter",
    description:
      "Of the promoter's holding, what percent is pledged as collateral (latest BSE filing).",
    formula: "pledged_shares / promoter_holding_shares × 100",
    tradingTakeaway:
      "<10% = clean; >50% = solvency / margin-call risk; cliff-style spikes preceded several distress cases historically.",
  },
  {
    key: "chng_in_prom_hld",
    label: "Δ Promoter %",
    category: "Promoter",
    description: "Quarter-over-quarter change in promoter holding %.",
    formula: "prom_hld_this_qtr − prom_hld_prev_qtr",
    tradingTakeaway:
      "Negative = promoters trimming (often a tell); positive = insider buying conviction.",
  },

  // ── Event ─────────────────────────────────────────────────
  {
    key: "event",
    label: "Latest Event",
    category: "Event",
    description:
      "Latest corporate event from the NSE corporate-actions feed (board meeting, dividend, results, AGM, etc.).",
    formula: "max(corporate_events.date) → corporate_events.event_type",
    tradingTakeaway:
      "Filters tickers with imminent catalysts. 'Results' events often coincide with delivery spikes.",
  },
  {
    key: "event_date",
    label: "Event Date",
    category: "Event",
    description: "Date of the latest corporate event.",
    formula: "max(corporate_events.date)",
    tradingTakeaway:
      "How fresh the catalyst is. Today / yesterday = high-impact window.",
  },
];

/** Group columns by category, preserving the order they
 *  appear in COLUMN_DOCS. */
export function groupByCategory(): {
  category: ColumnCategory;
  blurb: string;
  docs: ColumnDoc[];
}[] {
  const order: ColumnCategory[] = [
    "Identity",
    "Price",
    "Volume",
    "Delivery",
    "Notional",
    "Technical",
    "Fundamentals",
    "Promoter",
    "Event",
  ];
  return order.map((category) => ({
    category,
    blurb: CATEGORY_BLURBS[category],
    docs: COLUMN_DOCS.filter((d) => d.category === category),
  }));
}
