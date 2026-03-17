"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CompareContent } from "../compare/page";
import { apiFetch } from "@/lib/apiFetch";
import { useTheme } from "@/hooks/useTheme";
import { API_URL } from "@/lib/config";
import {
  PlotlyChart,
} from "@/components/charts/PlotlyChart";
import {
  buildForecastChart,
  buildForecastShapes,
} from "@/components/charts/chartBuilders";
import { StockChart } from "@/components/charts/StockChart";
import type {
  OHLCVResponse,
  IndicatorsResponse,
  ForecastSeriesResponse,
  ForecastsResponse,
  TickerForecast,
} from "@/lib/types";

// ---------------------------------------------------------------
// Types
// ---------------------------------------------------------------

type TabId = "analysis" | "forecast" | "compare";

// ---------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------

/** Currency symbol based on ticker suffix. */
function tickerCurrency(ticker: string): string {
  if (ticker.endsWith(".NS") || ticker.endsWith(".BO"))
    return "₹";
  return "$";
}

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div
      className="
        rounded-lg p-4
        bg-gray-50 dark:bg-gray-800/50
        border border-gray-100 dark:border-gray-700/50
      "
    >
      <p
        className="
          text-xs font-medium uppercase tracking-wider
          text-gray-400 dark:text-gray-500 mb-1
        "
      >
        {label}
      </p>
      <p
        className={`
          font-mono text-xl font-semibold
          ${color ?? "text-gray-900 dark:text-gray-100"}
        `}
      >
        {value}
      </p>
      {sub && (
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
          {sub}
        </p>
      )}
    </div>
  );
}

function ChartSkeleton({ h = "h-64" }: { h?: string }) {
  return (
    <div
      className={`
        flex items-center justify-center ${h}
        bg-gray-100 dark:bg-gray-800
        rounded-lg animate-pulse
      `}
    >
      <span className="text-sm text-gray-400">
        Loading chart...
      </span>
    </div>
  );
}

// ---------------------------------------------------------------
// Tab: Analysis
// ---------------------------------------------------------------

function AnalysisTab({ ticker }: { ticker: string }) {
  const [ohlcv, setOhlcv] =
    useState<OHLCVResponse | null>(null);
  const [indicators, setIndicators] =
    useState<IndicatorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const q = encodeURIComponent(ticker);
    Promise.all([
      apiFetch(
        `${API_URL}/dashboard/chart/ohlcv?ticker=${q}`,
      ).then((r) => {
        if (!r.ok) throw new Error(`OHLCV: HTTP ${r.status}`);
        return r.json() as Promise<OHLCVResponse>;
      }),
      apiFetch(
        `${API_URL}/dashboard/chart/indicators?ticker=${q}`,
      ).then((r) => {
        if (!r.ok) {
          throw new Error(`Indicators: HTTP ${r.status}`);
        }
        return r.json() as Promise<IndicatorsResponse>;
      }),
    ])
      .then(([o, ind]) => {
        if (cancelled) return;
        setOhlcv(o);
        setIndicators(ind);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const sym = tickerCurrency(ticker);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  // Map API data to StockChart format
  const chartOhlcv = useMemo(
    () =>
      ohlcv?.data.map((d) => ({
        date: d.date,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
        volume: d.volume,
      })) ?? [],
    [ohlcv],
  );

  const chartIndicators = useMemo(
    () =>
      indicators?.data.map((d) => ({
        date: d.date,
        sma_50: d.sma_50,
        sma_200: d.sma_200,
        rsi_14: d.rsi_14,
        macd: d.macd,
        macd_signal: d.macd_signal,
        macd_hist: d.macd_hist,
        bb_upper: d.bb_upper,
        bb_lower: d.bb_lower,
      })) ?? [],
    [indicators],
  );

  // --- Stats ---
  const stats = useMemo(() => {
    if (!ohlcv || !indicators) return null;
    const last = ohlcv.data[ohlcv.data.length - 1];
    const prev =
      ohlcv.data.length > 1
        ? ohlcv.data[ohlcv.data.length - 2]
        : last;
    const change = last.close - prev.close;
    const changePct =
      prev.close !== 0
        ? (change / prev.close) * 100
        : 0;
    const lastInd =
      indicators.data[indicators.data.length - 1];
    return { last, change, changePct, lastInd };
  }, [ohlcv, indicators]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <ChartSkeleton key={i} h="h-20" />
          ))}
        </div>
        <ChartSkeleton />
        <ChartSkeleton />
        <ChartSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="
          rounded-lg border border-red-200
          dark:border-red-800 bg-red-50
          dark:bg-red-900/20 px-5 py-10
          text-center text-sm text-red-600
          dark:text-red-400
        "
      >
        {error}
      </div>
    );
  }

  if (!stats) return null;

  const changeColor =
    stats.change >= 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-red-600 dark:text-red-400";

  const rsiVal = stats.lastInd?.rsi_14;
  let rsiColor = "text-gray-900 dark:text-gray-100";
  if (rsiVal != null) {
    if (rsiVal >= 70) {
      rsiColor = "text-red-600 dark:text-red-400";
    } else if (rsiVal <= 30) {
      rsiColor = "text-emerald-600 dark:text-emerald-400";
    }
  }

  const macdVal = stats.lastInd?.macd;
  const sigVal = stats.lastInd?.macd_signal;
  let macdSignalLabel = "--";
  let macdColor = "text-gray-900 dark:text-gray-100";
  if (macdVal != null && sigVal != null) {
    if (macdVal > sigVal) {
      macdSignalLabel = "Bullish";
      macdColor =
        "text-emerald-600 dark:text-emerald-400";
    } else {
      macdSignalLabel = "Bearish";
      macdColor = "text-red-600 dark:text-red-400";
    }
  }

  return (
    <div className="space-y-6">
      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Current Price"
          value={`${sym}${stats.last.close.toFixed(2)}`}
        />
        <StatCard
          label="Day Change"
          value={`${stats.change >= 0 ? "+" : ""}${sym}${Math.abs(stats.change).toFixed(2)}`}
          sub={`${stats.changePct >= 0 ? "+" : ""}${stats.changePct.toFixed(2)}%`}
          color={changeColor}
        />
        <StatCard
          label="RSI (14)"
          value={
            rsiVal != null ? rsiVal.toFixed(1) : "--"
          }
          sub={
            rsiVal != null
              ? rsiVal >= 70
                ? "Overbought"
                : rsiVal <= 30
                  ? "Oversold"
                  : "Neutral"
              : undefined
          }
          color={rsiColor}
        />
        <StatCard
          label="MACD Signal"
          value={macdSignalLabel}
          sub={
            macdVal != null
              ? `MACD: ${macdVal.toFixed(3)}`
              : undefined
          }
          color={macdColor}
        />
      </div>

      {/* TradingView chart: Candlestick + Volume + RSI + MACD */}
      <div
        className="
          rounded-xl border border-gray-200
          dark:border-gray-700 bg-white
          dark:bg-gray-900 shadow-sm p-2
        "
      >
        <StockChart
          ohlcv={chartOhlcv}
          indicators={chartIndicators}
          isDark={isDark}
          height={700}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------
// Tab: Forecast
// ---------------------------------------------------------------

type HorizonId = 3 | 6 | 9;

function ForecastTab({ ticker }: { ticker: string }) {
  const [ohlcv, setOhlcv] =
    useState<OHLCVResponse | null>(null);
  const [series, setSeries] =
    useState<ForecastSeriesResponse | null>(null);
  const [summary, setSummary] =
    useState<TickerForecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] =
    useState<HorizonId>(9);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const q = encodeURIComponent(ticker);
    Promise.all([
      apiFetch(
        `${API_URL}/dashboard/chart/ohlcv?ticker=${q}`,
      ).then((r) => {
        if (!r.ok) throw new Error(`OHLCV: HTTP ${r.status}`);
        return r.json() as Promise<OHLCVResponse>;
      }),
      apiFetch(
        `${API_URL}/dashboard/chart/forecast-series?ticker=${q}&horizon=9`,
      ).then((r) => {
        if (!r.ok) {
          throw new Error(`Forecast: HTTP ${r.status}`);
        }
        return r.json() as Promise<ForecastSeriesResponse>;
      }),
      apiFetch(
        `${API_URL}/dashboard/forecasts/summary`,
      ).then((r) => {
        if (!r.ok) {
          throw new Error(`Summary: HTTP ${r.status}`);
        }
        return r.json() as Promise<ForecastsResponse>;
      }),
    ])
      .then(([o, fs, sum]) => {
        if (cancelled) return;
        setOhlcv(o);
        setSeries(fs);
        const match = sum.forecasts.find(
          (f) =>
            f.ticker.toUpperCase() ===
            ticker.toUpperCase(),
        );
        setSummary(match ?? null);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [ticker]);

  // Truncate forecast series to selected horizon
  const truncatedSeries = useMemo(() => {
    if (!series || !series.data.length) return series;
    // 9M data ≈ ~270 points; scale by horizon ratio
    const maxPoints = Math.ceil(
      (series.data.length * horizon) / 9,
    );
    return {
      ...series,
      data: series.data.slice(0, maxPoints),
    };
  }, [series, horizon]);

  // --- Forecast chart traces ---
  const forecastTraces = useMemo(() => {
    if (!ohlcv || !truncatedSeries) return [];
    return buildForecastChart(
      ohlcv.data.map((d) => d.date),
      ohlcv.data.map((d) => d.close),
      truncatedSeries.data.map((d) => d.date),
      truncatedSeries.data.map((d) => d.predicted),
      truncatedSeries.data.map((d) => d.upper),
      truncatedSeries.data.map((d) => d.lower),
      ticker,
      summary?.sentiment,
    );
  }, [ohlcv, truncatedSeries, ticker, summary?.sentiment]);

  // --- Shapes + annotations (today line, price, targets) ---
  const { shapes, annotations } = useMemo(() => {
    const currentPrice =
      ohlcv && ohlcv.data.length > 0
        ? ohlcv.data[ohlcv.data.length - 1].close
        : null;
    // Only show targets up to selected horizon
    const targets = (summary?.targets ?? [])
      .filter((t) => t.horizon_months <= horizon)
      .map((t) => ({
        horizon_months: t.horizon_months,
        target_date: t.target_date,
        target_price: t.target_price,
        pct_change: t.pct_change,
      }));
    return buildForecastShapes(currentPrice, targets);
  }, [ohlcv, summary, horizon]);

  if (loading) {
    return (
      <div className="space-y-6">
        <ChartSkeleton />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <ChartSkeleton key={i} h="h-28" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="
          rounded-lg border border-red-200
          dark:border-red-800 bg-red-50
          dark:bg-red-900/20 px-5 py-10
          text-center text-sm text-red-600
          dark:text-red-400
        "
      >
        {error}
      </div>
    );
  }

  const targets = (summary?.targets ?? []).filter(
    (t) => t.horizon_months <= horizon,
  );
  const sym = tickerCurrency(ticker);

  return (
    <div className="space-y-6">
      {/* Forecast chart */}
      <div
        className="
          rounded-xl border border-gray-200
          dark:border-gray-700 bg-white
          dark:bg-gray-900 shadow-sm p-4
        "
      >
        <div
          className="
            flex flex-col sm:flex-row
            sm:items-center sm:justify-between
            gap-2 mb-3
          "
        >
          <div className="flex items-baseline gap-2">
            <h3
              className="
                text-sm font-semibold text-gray-900
                dark:text-gray-100
              "
            >
              Prophet Forecast
              {summary?.sentiment && (
                <span className="ml-1">
                  {summary.sentiment.toLowerCase().includes("bull")
                    ? "\u{1F7E2}"
                    : summary.sentiment.toLowerCase().includes("bear")
                      ? "\u{1F534}"
                      : "\u{1F7E1}"}
                  {" "}
                  {summary.sentiment}
                </span>
              )}
            </h3>
            {summary && (
              <span
                className="
                  text-xs text-gray-400
                  dark:text-gray-500
                "
              >
                as of {summary.run_date}
              </span>
            )}
          </div>
          {/* Horizon picker */}
          <div
            className="
              inline-flex rounded-lg
              bg-gray-100 dark:bg-gray-800 p-1
            "
          >
            {([3, 6, 9] as HorizonId[]).map((h) => (
              <button
                key={h}
                onClick={() => setHorizon(h)}
                className={`
                  px-3 py-1 text-xs font-medium
                  rounded-md transition-colors
                  ${
                    horizon === h
                      ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm"
                      : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                  }
                `}
              >
                {h}M
              </button>
            ))}
          </div>
        </div>
        <PlotlyChart
          data={forecastTraces}
          height={550}
          config={{ scrollZoom: true }}
          layout={{
            hovermode: "x unified",
            margin: { t: 30, r: 80, b: 40, l: 60 },
            shapes,
            annotations,
            xaxis: {
              rangeslider: { visible: false },
            },
            yaxis: {
              side: "right",
              tickformat: ",.0f",
            },
            legend: {
              orientation: "h",
              x: 0.5,
              xanchor: "center",
              y: 1.08,
              font: { size: 11 },
            },
          }}
        />
      </div>

      {/* Forecast target cards */}
      {targets.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {targets.map((target) => {
            const isPositive = target.pct_change >= 0;
            return (
              <div
                key={target.horizon_months}
                className="
                  rounded-lg p-4
                  bg-gray-50 dark:bg-gray-800/50
                  border border-gray-100
                  dark:border-gray-700/50
                "
              >
                <p
                  className="
                    text-xs font-medium uppercase
                    tracking-wider text-gray-400
                    dark:text-gray-500 mb-1
                  "
                >
                  {target.horizon_months}-month
                </p>
                <p
                  className="
                    text-xs text-gray-500
                    dark:text-gray-400 mb-2
                  "
                >
                  {target.target_date}
                </p>
                <p
                  className="
                    font-mono text-2xl font-semibold
                    text-gray-900 dark:text-gray-100
                    mb-1
                  "
                >
                  {sym}{target.target_price.toFixed(2)}
                </p>
                <span
                  className={`
                    inline-flex items-center px-2
                    py-0.5 rounded-full text-xs
                    font-medium
                    ${
                      isPositive
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                        : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                    }
                  `}
                >
                  {isPositive ? "+" : ""}
                  {target.pct_change.toFixed(2)}%
                </span>
                <p
                  className="
                    font-mono text-xs text-gray-400
                    dark:text-gray-500 mt-2
                  "
                >
                  {sym}{target.lower_bound.toFixed(2)}
                  {" \u2014 "}
                  {sym}{target.upper_bound.toFixed(2)}
                </p>
              </div>
            );
          })}
        </div>
      )}

      {/* Accuracy metrics */}
      {summary &&
        (summary.mae != null ||
          summary.rmse != null ||
          summary.mape != null) && (
        <div
          className="
              rounded-xl border border-gray-200
              dark:border-gray-700 bg-white
              dark:bg-gray-900 shadow-sm px-5 py-4
            "
        >
          <h3
            className="
                text-sm font-semibold text-gray-900
                dark:text-gray-100 mb-3
              "
          >
            Model Accuracy
          </h3>
          <div className="flex items-center gap-8">
            {summary.mae != null && (
              <div className="flex items-center gap-1.5">
                <span
                  className="
                      text-xs text-gray-400
                      dark:text-gray-500
                    "
                >
                  MAE
                </span>
                <span
                  className="
                      font-mono text-sm font-medium
                      text-gray-900 dark:text-gray-100
                    "
                >
                  {summary.mae.toFixed(2)}
                </span>
              </div>
            )}
            {summary.rmse != null && (
              <div className="flex items-center gap-1.5">
                <span
                  className="
                      text-xs text-gray-400
                      dark:text-gray-500
                    "
                >
                  RMSE
                </span>
                <span
                  className="
                      font-mono text-sm font-medium
                      text-gray-900 dark:text-gray-100
                    "
                >
                  {summary.rmse.toFixed(2)}
                </span>
              </div>
            )}
            {summary.mape != null && (
              <div className="flex items-center gap-1.5">
                <span
                  className="
                      text-xs text-gray-400
                      dark:text-gray-500
                    "
                >
                  MAPE
                </span>
                <span
                  className="
                      font-mono text-sm font-medium
                      text-gray-900 dark:text-gray-100
                    "
                >
                  {Number(summary.mape).toFixed(2)}%
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Tab: Compare
// ---------------------------------------------------------------

function CompareTab() {
  return <CompareContent />;
}

// ---------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------

const TABS: { id: TabId; label: string }[] = [
  { id: "analysis", label: "Analysis" },
  { id: "forecast", label: "Forecast" },
  { id: "compare", label: "Compare" },
];

// ---------------------------------------------------------------
// Inner page (needs useSearchParams inside Suspense)
// ---------------------------------------------------------------

function AnalysisPageInner() {
  const searchParams = useSearchParams();
  const tickerParam = searchParams.get("ticker");

  const [tickers, setTickers] = useState<string[]>([]);
  const [selectedTicker, setSelectedTicker] =
    useState<string>("");
  const [activeTab, setActiveTab] =
    useState<TabId>("analysis");
  const [tickersLoading, setTickersLoading] =
    useState(true);

  // Fetch user tickers
  useEffect(() => {
    let cancelled = false;

    apiFetch(`${API_URL}/users/me/tickers`)
      .then((r) => {
        if (!r.ok) {
          throw new Error(`Tickers: HTTP ${r.status}`);
        }
        return r.json();
      })
      .then((data: { tickers: string[] }) => {
        if (cancelled) return;
        const list = data.tickers ?? [];
        setTickers(list);
        // Use URL param if valid, otherwise first ticker
        if (
          tickerParam &&
          list
            .map((t: string) => t.toUpperCase())
            .includes(tickerParam.toUpperCase())
        ) {
          setSelectedTicker(tickerParam.toUpperCase());
        } else if (list.length > 0) {
          setSelectedTicker(list[0]);
        }
      })
      .catch(() => {
        // Silently fall back — user may have no tickers
      })
      .finally(() => {
        if (!cancelled) setTickersLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [tickerParam]);

  const handleTickerChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      setSelectedTicker(e.target.value);
    },
    [],
  );

  if (tickersLoading) {
    return (
      <div className="space-y-6 p-6">
        <ChartSkeleton h="h-12" />
        <ChartSkeleton />
      </div>
    );
  }

  if (tickers.length === 0 || !selectedTicker) {
    return (
      <div
        className="
          p-6 text-center text-sm text-gray-500
          dark:text-gray-400
        "
      >
        No tickers linked to your account. Add tickers
        from the{" "}
        <Link
          href="/analytics/marketplace"
          className="text-indigo-600 dark:text-indigo-400 underline"
        >
          Marketplace
        </Link>{" "}
        to get started.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Ticker selector + Tabs */}
      <div
        className="
          flex flex-col sm:flex-row
          sm:items-center sm:justify-between gap-4
        "
      >
        {/* Ticker dropdown (hidden on Compare tab) */}
        <div className={`flex items-center gap-2 ${activeTab === "compare" ? "invisible" : ""}`}>
          <label
            htmlFor="ticker-select"
            className="
              text-sm font-medium text-gray-700
              dark:text-gray-300
            "
          >
            Ticker:
          </label>
          <select
            id="ticker-select"
            value={selectedTicker}
            onChange={handleTickerChange}
            className="
              text-sm rounded-md px-3 py-1.5
              border border-gray-200
              dark:border-gray-700
              bg-white dark:bg-gray-800
              text-gray-900 dark:text-gray-100
              focus:outline-none focus:ring-2
              focus:ring-indigo-500/40
              min-w-[120px]
            "
          >
            {tickers.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        {/* Tab pills */}
        <div
          className="
            inline-flex rounded-lg
            bg-gray-100 dark:bg-gray-800 p-1
          "
        >
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                px-4 py-1.5 text-sm font-medium
                rounded-md transition-colors
                ${
                  activeTab === tab.id
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200"
                }
              `}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {activeTab === "analysis" && (
        <AnalysisTab ticker={selectedTicker} />
      )}
      {activeTab === "forecast" && (
        <ForecastTab ticker={selectedTicker} />
      )}
      {activeTab === "compare" && <CompareTab />}
    </div>
  );
}

// ---------------------------------------------------------------
// Page export (Suspense boundary for useSearchParams)
// ---------------------------------------------------------------

export default function AnalysisPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6 p-6">
          <ChartSkeleton h="h-12" />
          <ChartSkeleton />
        </div>
      }
    >
      <AnalysisPageInner />
    </Suspense>
  );
}
