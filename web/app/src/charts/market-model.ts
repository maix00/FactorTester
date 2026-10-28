import type { RangeBand } from "./runtime.ts";
export type MarketSettings = { source: string; interval: string; range: string; adjusted: boolean; zone: "product" | "system" | "utc"; nodeSource?: {route_id:string; source_ref:string; product_ref:string}; start?: string; end?: string };
export const DEFAULT_MARKET_SETTINGS: MarketSettings = { source: "", interval: "DAY1", range: "all", adjusted: false, zone: "product" };
export function priceRequest(product: string, contract: string | undefined, settings: MarketSettings): Record<string, unknown> {
  if (settings.range === "custom" && (!settings.start || !settings.end || settings.start > settings.end)) throw new Error("Invalid date range");
  return { ...(contract ? { contract_uid: contract } : { product_name: product }), adjusted: contract ? false : settings.adjusted, chart_mode: "fixed", chart_interval: settings.interval, max_points: 5000,
    ...(settings.nodeSource ? settings.nodeSource : settings.source ? { data_source: settings.source } : {}), ...(["day", "month", "year", "ytd"].includes(settings.range) ? { chart_range: settings.range } : {}),
    ...(settings.range === "custom" ? { start_date: settings.start, end_date: settings.end } : {}) };
}
export function termBands(rows: Record<string, any>[]): RangeBand[] {
  return rows.map((row) => ({ id: String(row.uid || row.contract || `${row.start}:${row.end}`), label: String(row.contract || row.uid || ""), start: Date.parse(row.start_ts || row.start), end: Date.parse(row.end_ts || row.end) + (row.end_ts ? 0 : 86400000) })).filter((band) => Number.isFinite(band.start) && Number.isFinite(band.end));
}
export function marketZone(settings: MarketSettings, productZone?: string): string {
  return settings.zone === "utc" ? "UTC" : settings.zone === "system" || !productZone ? Intl.DateTimeFormat().resolvedOptions().timeZone : productZone;
}
