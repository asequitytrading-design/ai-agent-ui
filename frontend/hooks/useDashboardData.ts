"use client";
/**
 * Generic data-fetching hook for dashboard widgets.
 *
 * Wraps ``apiFetch`` with loading/error state management
 * and AbortController cleanup on unmount.  Typed wrappers
 * for each endpoint are exported below.
 */

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/apiFetch";
import { API_URL } from "@/lib/config";
import type {
  WatchlistResponse,
  ForecastsResponse,
  AnalysisResponse,
  LLMUsageResponse,
} from "@/lib/types";

export interface DashboardData<T> {
  value: T | null;
  loading: boolean;
  error: string | null;
}

function useDashboardData<T>(
  endpoint: string,
): DashboardData<T> {
  const [value, setValue] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    apiFetch(`${API_URL}${endpoint}`, {
      signal: controller.signal,
    })
      .then((r) => {
        if (!r.ok) {
          throw new Error(`HTTP ${r.status}`);
        }
        return r.json();
      })
      .then((data: T) => {
        setValue(data);
        setError(null);
      })
      .catch((err: unknown) => {
        if (
          err instanceof Error &&
          err.name === "AbortError"
        ) {
          return;
        }
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load",
        );
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [endpoint]);

  return { value, loading, error };
}

// ---------------------------------------------------------------
// Typed wrappers
// ---------------------------------------------------------------

export function useWatchlist(): DashboardData<WatchlistResponse> {
  return useDashboardData<WatchlistResponse>(
    "/dashboard/watchlist",
  );
}

export function useForecastSummary(): DashboardData<ForecastsResponse> {
  return useDashboardData<ForecastsResponse>(
    "/dashboard/forecasts/summary",
  );
}

export function useAnalysisLatest(): DashboardData<AnalysisResponse> {
  return useDashboardData<AnalysisResponse>(
    "/dashboard/analysis/latest",
  );
}

export function useLLMUsage(): DashboardData<LLMUsageResponse> {
  return useDashboardData<LLMUsageResponse>(
    "/dashboard/llm-usage",
  );
}
