import { loadScript } from "../assets.ts";
import type { Indicator } from "./runtime.ts";
export type FactorSeries = { product?: string; name?: string; code?: string; layer?: string; factor_alias?: string; factor_ref?: string; math_expr?: string; dates: unknown[]; values: unknown[] };
export type FactorModel = { series: FactorSeries[]; factor: Record<string, any>; meta: Record<string, any>; payload: Record<string, any> };
declare global { interface Window { FTFactorSeriesModel?: { build: (value: unknown) => FactorModel; productIdentity: (item: FactorSeries) => string; priceRequest: (configuration: unknown, product: string, freq?: string) => Record<string, unknown> } } }
export async function loadFactorModel(): Promise<NonNullable<Window["FTFactorSeriesModel"]>> {
  if (!window.FTFactorSeriesModel) await loadScript("/research-static/test-modules/factor-evaluation/results/model.js");
  if (!window.FTFactorSeriesModel) throw new Error("Factor result model unavailable");
  return window.FTFactorSeriesModel;
}
export function seriesArtifact(items: Record<string, any>[], factorEvaluation = false): string | undefined {
  return items.find((item) => item.state === "active" && item.name === "factor_series_data")?.name
    || (factorEvaluation ? items.find((item) => item.state === "active" && item.name === "result")?.name : undefined);
}
export function factorIndicators(series: FactorSeries[], timestampOf: (time: unknown) => number): Indicator[] {
  return series.map((item, index) => ({ id: String(index), label: `F${index + 1}`, points: item.dates.map((date, position) => {
    const raw = item.values[position], numeric = Number(raw);
    return { timestamp: timestampOf(date), value: raw === null || raw === undefined || raw === "" || !Number.isFinite(numeric) ? null : numeric };
  }).filter((point) => Number.isFinite(point.timestamp)) }));
}

/** Use result observation bounds only when the frozen settings omit bounds. */
export function observationBounds(series: FactorSeries[], timestampOf: (time: unknown) => number): { start_date?: string; end_date?: string } {
  let first = Infinity, last = -Infinity;
  for (const item of series) for (const date of item.dates) {
    const value = timestampOf(date);
    if (Number.isFinite(value)) { first = Math.min(first, value); last = Math.max(last, value); }
  }
  return Number.isFinite(first) && Number.isFinite(last) ? { start_date: new Date(first).toISOString(), end_date: new Date(last).toISOString() } : {};
}
