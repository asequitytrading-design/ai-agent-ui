"use client";
/**
 * W5: Recommendations action cards (ASETPLTFRM-291).
 */

import { WidgetSkeleton } from "./WidgetSkeleton";
import { WidgetError } from "./WidgetError";
import type { DashboardData } from "@/hooks/useDashboardData";
import type { RecommendationsResponse } from "@/lib/types";

interface Props {
  data: DashboardData<RecommendationsResponse>;
}

function severityIcon(severity: string) {
  if (severity === "high") {
    return (
      <span className="text-red-500" title="High">
        <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
        </svg>
      </span>
    );
  }
  if (severity === "medium") {
    return (
      <span className="text-amber-500" title="Medium">
        <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd" />
        </svg>
      </span>
    );
  }
  return (
    <span className="text-blue-500" title="Low">
      <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd" />
      </svg>
    </span>
  );
}

function healthBadge(health: string) {
  const cls =
    health === "Healthy"
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
      : health === "Needs Attention"
        ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
        : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>
      {health}
    </span>
  );
}

export function RecommendationsWidget({ data }: Props) {
  if (data.loading) return <WidgetSkeleton className="h-72" />;
  if (data.error) return <WidgetError message={data.error} />;

  const resp = data.value;
  const recs = resp?.recommendations ?? [];
  const health = resp?.portfolio_health ?? "Healthy";

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm">
      <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Recommendations
          </h3>
          <div className="flex items-center gap-2">
            {healthBadge(health)}
            {recs.length > 0 && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {recs.length} suggestion{recs.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {recs.length === 0 ? (
          <div className="py-8 text-center">
            <span className="text-emerald-500 text-2xl">&#10003;</span>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
              Your portfolio looks well-balanced
            </p>
          </div>
        ) : (
          recs.map((r, i) => (
            <div
              key={`${r.type}-${r.ticker ?? i}`}
              className="flex items-start gap-3 px-5 py-3"
            >
              <div className="mt-0.5">
                {severityIcon(r.severity)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {r.title}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
                  {r.description}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
