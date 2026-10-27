import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_MARKET_SETTINGS, marketZone, priceRequest, termBands } from "./market-model.ts";
test("market selection freezes a fixed frequency and never changes range on chart zoom", () => {
  assert.deepEqual(priceRequest("AU.SHF", undefined, DEFAULT_MARKET_SETTINGS), { product_name: "AU.SHF", adjusted: false, chart_mode: "fixed", chart_interval: "DAY1", max_points: 5000 });
  assert.deepEqual(priceRequest("AU.SHF", "uid", { ...DEFAULT_MARKET_SETTINGS, source: "registered", interval: "SOURCE", range: "month", adjusted: true }), { contract_uid: "uid", adjusted: false, data_source: "registered", chart_mode: "fixed", chart_interval: "SOURCE", max_points: 5000, chart_range: "month" });
  assert.throws(() => priceRequest("p", undefined, { ...DEFAULT_MARKET_SETTINGS, range: "custom", start: "2025-02-01", end: "2025-01-01" }), /range/);
});
test("term ranges retain explicit timestamps and do not change request selection", () => {
  const settings = { ...DEFAULT_MARKET_SETTINGS };
  assert.deepEqual(termBands([{ uid: "x", start_ts: "2025-01-01T09:00:00+08:00", end_ts: "2025-01-01T15:00:00+08:00" }]), [{ id: "x", label: "x", start: Date.parse("2025-01-01T01:00:00Z"), end: Date.parse("2025-01-01T07:00:00Z") }]);
  assert.deepEqual(priceRequest("p", undefined, settings), priceRequest("p", undefined, DEFAULT_MARKET_SETTINGS));
  assert.equal(marketZone(settings, "Asia/Shanghai"), "Asia/Shanghai");
});
