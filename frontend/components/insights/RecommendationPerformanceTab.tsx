"use client";
/**
 * Cohort-bucketed performance view for the
 * recommendations panel — sibling sub-tab to the
 * existing History list.
 *
 * A *cohort* bucket groups recommendations by when
 * they were issued (week / month / quarter, IST).
 * Each bucket carries 30/60/90-day outcome metrics
 * already computed by the daily recommendation_outcomes
 * job. Latest run still surfaces via the dashboard
 * widget — this tab is for "how have past cohorts
 * actually performed".
 */

import { useMemo, useState } from "react";
import { useRecommendationPerformance } from
  "@/hooks/useInsightsData";
import { SimpleBarChart, type BarSeries } from
  "@/components/charts/SimpleBarChart";
import { DownloadCsvButton } from
  "@/components/common/DownloadCsvButton";
import type { PerfBucket } from "@/lib/types";

type Granularity = "week" | "month" | "quarter";
type Scope = "all" | "india" | "us";

const GRANULARITIES: {
  value: Granularity;
  label: string;
}[] = [
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "quarter", label: "Quarterly" },
];

const SCOPES: { value: Scope; label: string }[] = [
  { value: "all", label: "All" },
  { value: "india", label: "India" },
  { value: "us", label: "US" },
];

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v.toFixed(1)}%`;
}

function fmtReturn(
  v: number | null | undefined,
): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function returnColor(
  v: number | null | undefined,
): string {
  if (v == null) return "text-gray-500";
  if (v > 0) return "text-emerald-600 dark:text-emerald-400";
  if (v < 0) return "text-rose-600 dark:text-rose-400";
  return "text-gray-500";
}

interface KpiTileProps {
  label: string;
  value: string;
  tooltip: string;
  valueClass?: string;
}

function KpiTile({
  label, value, tooltip, valueClass,
}: KpiTileProps) {
  return (
    <div
      className={
        "rounded-md border border-gray-200 " +
        "dark:border-gray-700 bg-white " +
        "dark:bg-gray-800 px-3 py-2"
      }
      title={tooltip}
    >
      <div
        className={
          "text-[10px] uppercase tracking-wide " +
          "text-gray-500 dark:text-gray-400"
        }
      >
        {label}
      </div>
      <div
        className={
          "mt-0.5 text-base font-semibold " +
          (valueClass
            ?? "text-gray-900 dark:text-gray-100")
        }
      >
        {value}
      </div>
    </div>
  );
}

interface PillStripProps<T extends string> {
  options: { value: T; label: string }[];
  selected: T;
  onChange: (v: T) => void;
}

function PillStrip<T extends string>({
  options, selected, onChange,
}: PillStripProps<T>) {
  return (
    <div className="inline-flex rounded-md border border-gray-300 dark:border-gray-600 overflow-hidden">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={
            "px-2.5 py-1 text-xs font-medium " +
            "transition-colors " +
            (selected === o.value
              ? "bg-indigo-600 text-white"
              : "bg-white dark:bg-gray-800 " +
                "text-gray-700 dark:text-gray-200 " +
                "hover:bg-gray-100 " +
                "dark:hover:bg-gray-700")
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function buildCsv(buckets: PerfBucket[]): string {
  const cols: (keyof PerfBucket)[] = [
    "bucket_label",
    "bucket_start",
    "total_recs",
    "acted_on_count",
    "pending_count",
    "hit_rate_30d",
    "hit_rate_60d",
    "hit_rate_90d",
    "avg_return_30d",
    "avg_return_60d",
    "avg_return_90d",
    "avg_excess_30d",
    "avg_excess_60d",
    "avg_excess_90d",
  ];
  const header = cols.join(",");
  const lines = buckets.map((b) =>
    cols
      .map((c) => {
        const v = b[c];
        if (v == null) return "";
        return String(v);
      })
      .join(","),
  );
  return [header, ...lines].join("\n");
}

export function RecommendationPerformanceTab() {
  const [granularity, setGranularity] =
    useState<Granularity>("month");
  const [scope, setScope] = useState<Scope>("all");
  const [actedOnOnly, setActedOnOnly] =
    useState<boolean>(false);

  const perf = useRecommendationPerformance({
    granularity,
    scope,
    actedOnOnly,
    monthsBack: 14,
  });

  // Wrap fallbacks in useMemo so dep identity is
  // stable across renders (eslint-plugin-react-hooks
  // v5 flags ?? [] inside another hook's deps).
  const buckets = useMemo(
    () => perf.value?.buckets ?? [],
    [perf.value?.buckets],
  );
  const summary = perf.value?.summary;
  const totalPending =
    summary?.pending_count ?? 0;

  // Bar chart 1: hit rate per bucket × horizon.
  const hitRateChart = useMemo(() => {
    const categories = buckets.map((b) => b.bucket_label);
    const series: BarSeries[] = [
      {
        name: "30d",
        values: buckets.map((b) => b.hit_rate_30d ?? 0),
      },
      {
        name: "60d",
        values: buckets.map((b) => b.hit_rate_60d ?? 0),
      },
      {
        name: "90d",
        values: buckets.map((b) => b.hit_rate_90d ?? 0),
      },
    ];
    return { categories, series };
  }, [buckets]);

  // Bar chart 2: avg return vs benchmark per bucket
  // (90d horizon — the most stable signal).
  const returnChart = useMemo(() => {
    const categories = buckets.map((b) => b.bucket_label);
    const recReturn = buckets.map(
      (b) => b.avg_return_90d ?? 0,
    );
    const benchReturn = buckets.map((b) => {
      const r = b.avg_return_90d;
      const e = b.avg_excess_90d;
      if (r == null || e == null) return 0;
      return r - e;
    });
    const series: BarSeries[] = [
      { name: "Recommendation", values: recReturn },
      { name: "Benchmark", values: benchReturn },
    ];
    return { categories, series };
  }, [buckets]);

  const handleDownload = () => {
    const csv = buildCsv(buckets);
    const blob = new Blob([csv], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (
      `recommendation-performance-${granularity}` +
      `-${scope}.csv`
    );
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      {/* ── Filter row ──────────────────────────── */}
      <div
        className={
          "flex flex-wrap items-center gap-2 " +
          "justify-between"
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span
              className={
                "text-[11px] uppercase tracking-wide " +
                "text-gray-500 dark:text-gray-400"
              }
            >
              Period
            </span>
            <PillStrip
              options={GRANULARITIES}
              selected={granularity}
              onChange={setGranularity}
            />
          </div>
          <div className="flex items-center gap-2">
            <span
              className={
                "text-[11px] uppercase tracking-wide " +
                "text-gray-500 dark:text-gray-400"
              }
            >
              Scope
            </span>
            <PillStrip
              options={SCOPES}
              selected={scope}
              onChange={setScope}
            />
          </div>
          <label
            className={
              "inline-flex items-center gap-1.5 " +
              "text-xs text-gray-700 " +
              "dark:text-gray-300 cursor-pointer"
            }
          >
            <input
              type="checkbox"
              checked={actedOnOnly}
              onChange={(e) =>
                setActedOnOnly(e.target.checked)
              }
              className="h-3.5 w-3.5"
              data-testid="acted-on-toggle"
            />
            Acted-on only
          </label>
        </div>
        <DownloadCsvButton
          onClick={handleDownload}
          disabled={buckets.length === 0}
          data-testid="perf-csv"
        />
      </div>

      {/* ── KPI tiles ───────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiTile
          label="Total recs"
          value={String(summary?.total_recs ?? 0)}
          tooltip="Recommendations issued in window"
        />
        <KpiTile
          label="Acted on"
          value={String(summary?.acted_on_count ?? 0)}
          tooltip="Recs the user acted on"
        />
        <KpiTile
          label="Hit rate 90d"
          value={fmtPct(summary?.hit_rate_90d)}
          tooltip="Beat-benchmark rate at 90 days"
        />
        <KpiTile
          label="Avg excess 90d"
          value={fmtReturn(summary?.avg_excess_90d)}
          valueClass={returnColor(
            summary?.avg_excess_90d,
          )}
          tooltip="Avg excess return vs benchmark at 90d"
        />
      </div>

      {/* ── Stale chip ──────────────────────────── */}
      {totalPending > 0 && (
        <div
          className={
            "inline-flex items-center gap-1.5 " +
            "rounded-full bg-amber-50 " +
            "dark:bg-amber-900/30 border " +
            "border-amber-300 dark:border-amber-700 " +
            "px-2.5 py-1 text-xs " +
            "text-amber-800 dark:text-amber-200"
          }
          title={
            "Recommendations younger than 30 days " +
            "have no outcomes yet — they will appear " +
            "in the metrics once the daily " +
            "recommendation_outcomes job processes them."
          }
        >
          ⚠ {totalPending} recommendation
          {totalPending === 1 ? "" : "s"} under 30 days,
          outcomes pending
        </div>
      )}

      {/* ── Loading / empty states ───────────────── */}
      {perf.loading && (
        <div
          className={
            "flex items-center justify-center h-32 " +
            "text-sm text-gray-500 " +
            "dark:text-gray-400"
          }
        >
          Loading performance data…
        </div>
      )}
      {perf.error && (
        <div className="text-sm text-rose-600 dark:text-rose-400">
          Failed to load performance: {perf.error}
        </div>
      )}
      {!perf.loading
        && !perf.error
        && buckets.length === 0 && (
        <div
          className={
            "rounded border border-dashed " +
            "border-gray-300 dark:border-gray-600 " +
            "p-8 text-center text-sm " +
            "text-gray-500 dark:text-gray-400"
          }
        >
          <p className="font-medium">
            No recommendations in this window.
          </p>
          <p className="mt-1 text-xs">
            Try widening the period or switching scope.
          </p>
        </div>
      )}

      {/* ── Charts ──────────────────────────────── */}
      {!perf.loading
        && !perf.error
        && buckets.length > 0 && (
        <div className="space-y-4">
          <div
            className={
              "rounded-md border border-gray-200 " +
              "dark:border-gray-700 bg-white " +
              "dark:bg-gray-800 p-3"
            }
          >
            <SimpleBarChart
              categories={hitRateChart.categories}
              series={hitRateChart.series}
              title="Hit rate by horizon"
              yAxisLabel="%"
              height={280}
              valueFormatter={(v) =>
                `${v.toFixed(1)}%`
              }
            />
          </div>
          <div
            className={
              "rounded-md border border-gray-200 " +
              "dark:border-gray-700 bg-white " +
              "dark:bg-gray-800 p-3"
            }
          >
            <SimpleBarChart
              categories={returnChart.categories}
              series={returnChart.series}
              title="Avg 90d return vs benchmark"
              yAxisLabel="%"
              height={280}
              valueFormatter={(v) =>
                `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}
