"use client";
/**
 * W4: News & Sentiment widget (ASETPLTFRM-290).
 */

import { WidgetSkeleton } from "./WidgetSkeleton";
import { WidgetError } from "./WidgetError";
import type { DashboardData } from "@/hooks/useDashboardData";
import type { PortfolioNewsResponse } from "@/lib/types";

interface Props {
  data: DashboardData<PortfolioNewsResponse>;
}

function sentimentColor(label: string): string {
  if (label === "Bullish") return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
  if (label === "Bearish") return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
  return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
}

function timeAgo(dateStr: string): string {
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const hrs = Math.floor(diff / 3_600_000);
    if (hrs < 1) return "Just now";
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days === 1) return "Yesterday";
    return `${days}d ago`;
  } catch {
    return "";
  }
}

export function NewsWidget({ data }: Props) {
  if (data.loading) return <WidgetSkeleton className="h-72" />;
  if (data.error) return <WidgetError message={data.error} />;

  const resp = data.value;
  const headlines = resp?.headlines ?? [];

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm">
      <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            News & Sentiment
          </h3>
          <div className="flex gap-2">
            {resp && (
              <>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${sentimentColor(resp.portfolio_sentiment_label)}`}>
                  Portfolio: {resp.portfolio_sentiment_label} ({resp.portfolio_sentiment > 0 ? "+" : ""}{resp.portfolio_sentiment.toFixed(2)})
                </span>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {headlines.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">
            No recent news for your holdings
          </p>
        ) : (
          headlines.slice(0, 8).map((h, i) => (
            <a
              key={`${h.url}-${i}`}
              href={h.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-3 px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-900 dark:text-gray-100 line-clamp-2">
                  {h.title}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-gray-400">
                    {h.source}
                  </span>
                  {h.ticker && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
                      {h.ticker}
                    </span>
                  )}
                  <span className="text-xs text-gray-400">
                    {timeAgo(h.published_at)}
                  </span>
                </div>
              </div>
            </a>
          ))
        )}
      </div>
    </div>
  );
}
