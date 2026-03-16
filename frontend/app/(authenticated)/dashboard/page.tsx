"use client";
/**
 * Native dashboard page — Variant C asymmetric grid layout.
 *
 * A global country filter (India / US) in the hero card
 * filters all dashboard sections. Default: India.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { apiFetch } from "@/lib/apiFetch";
import { API_URL } from "@/lib/config";
import type { UserProfile } from "@/hooks/useEditProfile";
import type {
  WatchlistResponse,
  ForecastsResponse,
  AnalysisResponse,
} from "@/lib/types";
import { useChatContext } from "@/providers/ChatProvider";
import {
  useWatchlist,
  useForecastSummary,
  useAnalysisLatest,
  useLLMUsage,
  type DashboardData,
} from "@/hooks/useDashboardData";
import { HeroSection } from "@/components/widgets/HeroSection";
import { WatchlistWidget } from "@/components/widgets/WatchlistWidget";
import { AnalysisSignalsWidget } from "@/components/widgets/AnalysisSignalsWidget";
import { LLMUsageWidget } from "@/components/widgets/LLMUsageWidget";
import { ForecastChartWidget } from "@/components/widgets/ForecastChartWidget";

export type MarketFilter = "india" | "us";

export default function DashboardPage() {
  const [profile, setProfile] =
    useState<UserProfile | null>(null);
  const [marketFilter, setMarketFilter] =
    useState<MarketFilter>("india");
  const [selectedTicker, setSelectedTicker] =
    useState<string | null>(null);
  const { openPanel } = useChatContext();

  const watchlist = useWatchlist();
  const forecasts = useForecastSummary();
  const analysis = useAnalysisLatest();
  const llmUsage = useLLMUsage();

  // Fetch profile for hero greeting
  useEffect(() => {
    const controller = new AbortController();
    apiFetch(`${API_URL}/auth/me`, {
      signal: controller.signal,
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: UserProfile | null) => {
        if (data) setProfile(data);
      })
      .catch((err: unknown) => {
        if (
          err instanceof Error &&
          err.name === "AbortError"
        )
          return;
      });
    return () => controller.abort();
  }, []);

  // -------------------------------------------------------
  // Filter all data by selected market
  // -------------------------------------------------------

  const filteredWatchlist = useMemo<
    DashboardData<WatchlistResponse>
  >(() => {
    if (!watchlist.value) return watchlist;
    const tickers = watchlist.value.tickers.filter(
      (t) => t.market === marketFilter,
    );
    const totalValue = tickers.reduce(
      (sum, t) => sum + t.current_price,
      0,
    );
    const totalPrev = tickers.reduce(
      (sum, t) => sum + t.previous_close,
      0,
    );
    const dailyChg = totalValue - totalPrev;
    const dailyPct = totalPrev
      ? (dailyChg / totalPrev) * 100
      : 0;
    return {
      ...watchlist,
      value: {
        tickers,
        portfolio_value: Math.round(totalValue * 100) / 100,
        daily_change: Math.round(dailyChg * 100) / 100,
        daily_change_pct: Math.round(dailyPct * 100) / 100,
      },
    };
  }, [watchlist, marketFilter]);

  const filteredForecasts = useMemo<
    DashboardData<ForecastsResponse>
  >(() => {
    if (!forecasts.value) return forecasts;
    const filtered = forecasts.value.forecasts.filter(
      (f) => {
        const isIndia =
          f.ticker.endsWith(".NS") ||
          f.ticker.endsWith(".BO");
        return marketFilter === "india"
          ? isIndia
          : !isIndia;
      },
    );
    return {
      ...forecasts,
      value: { forecasts: filtered },
    };
  }, [forecasts, marketFilter]);

  const filteredAnalysis = useMemo<
    DashboardData<AnalysisResponse>
  >(() => {
    if (!analysis.value) return analysis;
    const filtered = analysis.value.analyses.filter(
      (a) => {
        const isIndia =
          a.ticker.endsWith(".NS") ||
          a.ticker.endsWith(".BO");
        return marketFilter === "india"
          ? isIndia
          : !isIndia;
      },
    );
    return {
      ...analysis,
      value: { analyses: filtered },
    };
  }, [analysis, marketFilter]);

  // Auto-select first ticker when filtered list changes
  useEffect(() => {
    const tickers =
      filteredWatchlist.value?.tickers ?? [];
    if (
      tickers.length > 0 &&
      (!selectedTicker ||
        !tickers.find(
          (t) => t.ticker === selectedTicker,
        ))
    ) {
      setSelectedTicker(tickers[0].ticker);
    }
  }, [filteredWatchlist.value, selectedTicker]);

  // Filter analysis to only the selected ticker
  const selectedAnalysis = useMemo<
    DashboardData<AnalysisResponse>
  >(() => {
    if (!filteredAnalysis.value || !selectedTicker)
      return filteredAnalysis;
    const analyses =
      filteredAnalysis.value.analyses.filter(
        (a) => a.ticker === selectedTicker,
      );
    return {
      ...filteredAnalysis,
      value: { analyses },
    };
  }, [filteredAnalysis, selectedTicker]);

  // Quick action: open chat with pre-filled prompt
  const handleQuickAction = useCallback(
    (prompt: string) => {
      openPanel();
      setTimeout(() => {
        const input = document.querySelector(
          '[data-testid="chat-message-input"]',
        ) as HTMLTextAreaElement | null;
        if (input) {
          const nativeSetter =
            Object.getOwnPropertyDescriptor(
              window.HTMLTextAreaElement.prototype,
              "value",
            )?.set;
          nativeSetter?.call(input, prompt);
          input.dispatchEvent(
            new Event("input", { bubbles: true }),
          );
          input.focus();
        }
      }, 350);
    },
    [openPanel],
  );

  return (
    <div className="p-4 md:p-6 space-y-4 md:space-y-6 max-w-[1600px] mx-auto">
      {/* Hero — full width, owns the global filter */}
      <HeroSection
        watchlist={filteredWatchlist}
        profile={profile}
        marketFilter={marketFilter}
        onMarketFilterChange={setMarketFilter}
        onQuickAction={handleQuickAction}
      />

      {/* Asymmetric grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-4 md:gap-6">
        <WatchlistWidget
          data={filteredWatchlist}
          selectedTicker={selectedTicker}
          onSelectTicker={setSelectedTicker}
        />

        <div className="space-y-4 md:space-y-6">
          <AnalysisSignalsWidget
            data={selectedAnalysis}
          />
          <LLMUsageWidget data={llmUsage} />
        </div>
      </div>

      {/* Forecast — full width */}
      <ForecastChartWidget
        data={filteredForecasts}
        marketFilter={marketFilter}
      />
    </div>
  );
}
