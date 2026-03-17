# TradingView Lightweight Charts — Analysis Page

## Migration: Plotly → lightweight-charts v5
Replaced `plotly.js-basic-dist` (which lacked candlestick support) with
TradingView's `lightweight-charts` (~45 KB vs ~3-8 MB).

## Component: `frontend/components/charts/StockChart.tsx`
Multi-pane stock chart using HTML5 Canvas rendering.

### Pane Layout
1. **Price** (main pane): Candlestick OHLC + SMA 50 (dashed amber) + SMA 200 (dotted red) + Bollinger Bands
2. **Volume** (`chart.addPane()`): Histogram colored by close vs open
3. **RSI** (`chart.addPane()`): Line chart with 70/30 price lines (Overbought/Oversold)
4. **MACD** (`chart.addPane()`): MACD line + Signal line (dashed) + Histogram (green/red)

### Key API Patterns
```typescript
import { createChart, CandlestickSeries, LineSeries, HistogramSeries } from "lightweight-charts";

const chart = createChart(container, options);
chart.addSeries(CandlestickSeries, { upColor, downColor, ... });
const volumePane = chart.addPane();
volumePane.addSeries(HistogramSeries, { ... });
```

### Notes
- `lineWidth` only accepts integers (1, 2, 3, 4) — not 1.5
- Time values are strings "YYYY-MM-DD" cast as `Time` type
- `setVisibleRange({ from, to })` for default 6-month view
- `ResizeObserver` for responsive width
- Dark mode: pass `isDark` prop → adjusts background, text, grid colors
- Cleanup: `chart.remove()` on unmount

## What Still Uses Plotly
- Forecast chart (line + confidence band fill — no fill-between in lightweight-charts)
- Correlation heatmap (no heatmap support)
- Insights bar charts
- These use `plotly.js-basic-dist` which handles scatter/bar/heatmap fine

## Package
`lightweight-charts: ^5.1.0` in `frontend/package.json`
