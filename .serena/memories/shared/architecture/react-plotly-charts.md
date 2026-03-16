# react-plotly.js Chart Integration

## Setup
- Packages: `react-plotly.js`, `plotly.js`, `@types/react-plotly.js`
- Wrapper: `frontend/components/charts/PlotlyChart.tsx`
- Builders: `frontend/components/charts/chartBuilders.ts`

## SSR Safety
Plotly requires `window`/`document`. Must use dynamic import:
```typescript
const Plot = dynamic(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => <LoadingSkeleton />,
});
```

## Auto Dark/Light Theming
PlotlyChart reads `useTheme()` and applies matching colors:
- Light: gray text (#374151), light grid (#e5e7eb)
- Dark: gray-400 text (#9ca3af), soft grid (rgba(156,163,175,0.15))
- Transparent backgrounds (chart inherits card bg)

## Color Palette (CHART_COLORS)
indigo, violet, pink, amber, emerald, blue, red, cyan

## Unified Subplot Pattern
For linked charts (Price+Volume+RSI+MACD), use a single PlotlyChart with multiple y-axes:
```typescript
// Assign traces to different y-axes
{ ...candlestickTrace, yaxis: "y" }    // price
{ ...volumeTrace, yaxis: "y2" }         // volume
{ ...rsiTrace, yaxis: "y3" }            // RSI
{ ...macdTrace, yaxis: "y4" }           // MACD

// Layout domains (stacked vertically)
yaxis:  { domain: [0.45, 1] }     // price 55%
yaxis2: { domain: [0.36, 0.44] }  // volume 8%
yaxis3: { domain: [0.18, 0.34] }  // RSI 16%
yaxis4: { domain: [0, 0.16] }     // MACD 16%
```
All share the same `xaxis` — zoom/pan/range selector applies to all.

## Range Selector
```typescript
xaxis: {
  rangeselector: {
    buttons: [
      { count: 3, label: "3M", step: "month", stepmode: "backward" },
      { count: 6, label: "6M", step: "month", stepmode: "backward" },
      { count: 1, label: "1Y", step: "year", stepmode: "backward" },
      { step: "all", label: "Max" },
    ],
    activecolor: "#6366f1",
  },
  rangeslider: { visible: false },
}
```

## Chart Types Used
- Candlestick: OHLC price chart (green increasing, red decreasing)
- Line: SMA, EMA, RSI, MACD signal
- Bar: Volume, MACD histogram
- Heatmap: Correlation matrix (RdBu colorscale)
- Scatter+fill: Bollinger Bands, forecast confidence band

## Theme-Aware Bollinger Bands
```typescript
const bbColor = isDark ? "rgba(165,180,252,0.45)" : "rgba(99,102,241,0.25)";
const bbFill = isDark ? "rgba(165,180,252,0.12)" : "rgba(99,102,241,0.06)";
```
