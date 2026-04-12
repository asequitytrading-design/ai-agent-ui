"use client";

import { useState } from "react";
import {
  useRecommendationHistory,
  useRecommendationStats,
} from "@/hooks/useInsightsData";
import type {
  HistoryRunItem,
  RecommendationStatsResponse,
} from "@/lib/types";

// ---------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------

function KpiCard({
  label,
  value,
  suffix = "",
  tooltip,
}: {
  label: string;
  value: string | number | null | undefined;
  suffix?: string;
  tooltip?: string;
}) {
  const display =
    value == null ? "\u2014" : `${value}${suffix}`;
  return (
    <div
      className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900/80 p-5 flex flex-col gap-1"
      title={tooltip}
    >
      <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
        {label}
      </span>
      <span className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
        {display}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------
// Health badge
// ---------------------------------------------------------------

function healthColor(score: number): string {
  if (score >= 80)
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
  if (score >= 60)
    return "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400";
  return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
}

// ---------------------------------------------------------------
// Collapsible run row
// ---------------------------------------------------------------

function RunRow({ run }: { run: HistoryRunItem }) {
  const [open, setOpen] = useState(false);
  const date = new Date(run.run_date);
  const formatted = date.toLocaleDateString("en-IN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  const adoptionPct =
    run.total_recommendations > 0
      ? (
          (run.acted_on_count /
            run.total_recommendations) *
          100
        ).toFixed(0)
      : "0";

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((p) => !p)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
            {formatted}
          </span>
          <span
            className={`px-2 py-0.5 rounded text-xs font-medium ${healthColor(run.health_score)}`}
          >
            {run.health_label} ({run.health_score})
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400 shrink-0">
          <span>
            {run.total_recommendations} recs
          </span>
          <span>
            {run.acted_on_count} acted on
          </span>
          <svg
            className={`w-4 h-4 transition-transform ${open ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </div>
      </button>

      {open && (
        <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/30">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-gray-500 dark:text-gray-400">
                Run ID
              </span>
              <p className="font-mono text-xs text-gray-700 dark:text-gray-300 truncate">
                {run.run_id}
              </p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">
                Health Score
              </span>
              <p className="font-semibold text-gray-900 dark:text-gray-100">
                {run.health_score}/100
              </p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">
                Total Recommendations
              </span>
              <p className="font-semibold text-gray-900 dark:text-gray-100">
                {run.total_recommendations}
              </p>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">
                Adoption
              </span>
              <p className="font-semibold text-gray-900 dark:text-gray-100">
                {adoptionPct}% ({run.acted_on_count}/
                {run.total_recommendations})
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Stats KPI row
// ---------------------------------------------------------------

function StatsRow({
  stats,
}: {
  stats: RecommendationStatsResponse;
}) {
  const fmtPct = (
    v: number | null | undefined,
  ): string => {
    if (v == null) return "\u2014";
    return `${v.toFixed(1)}%`;
  };

  const fmtReturn = (
    v: number | null | undefined,
  ): string => {
    if (v == null) return "\u2014";
    return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  };

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <KpiCard
        label="Hit Rate 30d"
        value={fmtPct(stats.hit_rate_30d)}
        tooltip="Percentage of recommendations that moved in the predicted direction within 30 days"
      />
      <KpiCard
        label="Hit Rate 60d"
        value={fmtPct(stats.hit_rate_60d)}
        tooltip="Percentage of recommendations that moved in the predicted direction within 60 days"
      />
      <KpiCard
        label="Avg Excess Return"
        value={fmtReturn(stats.avg_return_30d)}
        tooltip="Average return of recommendations vs Nifty 50 benchmark at 30 days"
      />
      <KpiCard
        label="Adoption Rate"
        value={fmtPct(stats.adoption_rate_pct)}
        tooltip="Percentage of recommendations that were acted on by users"
      />
    </div>
  );
}

// ---------------------------------------------------------------
// Main component
// ---------------------------------------------------------------

export function RecommendationHistoryTab() {
  const history = useRecommendationHistory(6);
  const stats = useRecommendationStats();

  if (history.loading || stats.loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-24 rounded-2xl bg-gray-200 dark:bg-gray-700"
            />
          ))}
        </div>
        <div className="h-48 rounded-xl bg-gray-200 dark:bg-gray-700" />
      </div>
    );
  }

  if (history.error || stats.error) {
    return (
      <div className="rounded-2xl border border-red-200 dark:border-red-800 bg-white dark:bg-gray-900/80 p-5 text-red-600 dark:text-red-400">
        Failed to load recommendation history.
        Please try again later.
      </div>
    );
  }

  const runs = history.value?.runs ?? [];
  const statsData = stats.value;

  if (runs.length === 0 && !statsData) {
    return (
      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900/80 p-8 text-center text-gray-500 dark:text-gray-400">
        No recommendation history. Generate
        recommendations from the dashboard first.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      {statsData && <StatsRow stats={statsData} />}

      {/* Monthly run timeline */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
          Run History
        </h3>
        {runs.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No runs recorded yet.
          </p>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <RunRow key={run.run_id} run={run} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
