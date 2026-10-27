import { loadScript } from "../assets.ts";
export type MarketBar = { timestamp: number; open: number; high: number; low: number; close: number; volume: number | null; openInterest: number | null };
export type RangeBand = { id: string; label: string; start: number; end: number };
export type PriceHandle = (() => void) & { setTimeZone: (zone: string) => void; setRangeBands: (bands: RangeBand[]) => void; selectRangeBand: (id: string) => boolean; fitContent: () => void };
export type Indicator = { id: string; label: string; points: { timestamp: number; value: number | null }[] };
declare global { interface Window {
  FTPriceChart?: { barsOf: (payload: unknown) => MarketBar[] };
  FTChartWorkbench?: {
    mountPriceChart: (host: HTMLElement, options: { bars: MarketBar[]; hasOpenInterest?: boolean; timeZone?: string; translate: (label: string) => string }) => PriceHandle;
    mountFactorChart: (host: HTMLElement, options: { bars: MarketBar[]; indicators: Indicator[]; product: string; loadRange: () => Promise<null>; translate: (label: string) => string }) => { dispose: () => void };
  };
} }
let ready: Promise<void> | undefined;
export function loadChartRuntime(): Promise<void> {
  if (!ready) ready = (async () => {
    // Reuse the existing codec and renderer; do not fork OHLC parsing or zoom.
    if (!window.FTPriceChart) await loadScript("/research-static/core/price-chart.js");
    if (!(window as Window & { LightweightCharts?: unknown }).LightweightCharts) await loadScript("/research-static/vendor/lightweight-charts/lightweight-charts.standalone.production.js");
    if (!window.FTChartWorkbench) await loadScript("/research-static/vendor/chart-workbench/chart-workbench.js");
    if (!window.FTPriceChart || !window.FTChartWorkbench) throw new Error("Chart runtime unavailable");
  })().catch((reason) => { ready = undefined; throw reason; });
  return ready;
}
