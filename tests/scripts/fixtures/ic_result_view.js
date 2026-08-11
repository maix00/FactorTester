const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "ic-result-view.js",
});
const artifacts = [
  {name: "ic_series_data", state: "active"},
  {name: "ic_statistics_data", state: "active"},
  {name: "ic_holding_half_life_data", state: "active"},
  {name: "ic_series_report", state: "active"},
  {name: "ic_rolling_stability_data", state: "deleted"},
];
assert.equal(window.FTICResults.supports(artifacts), true);
assert.deepEqual(
  window.FTICResults.relevantArtifacts(artifacts).map(item => item.name),
  ["ic_series_data", "ic_statistics_data", "ic_holding_half_life_data"],
);
assert.equal(window.FTICResults.supports([
  {name: "equity_curve_data", state: "active"},
]), false);
assert.equal(window.FTICResults.productGroupRef({
  payload: {
    analyses: {ic: {product_path_selection_id: "product-group:night"}},
  },
}), "product-group:night");
assert.equal(window.FTICResults.productGroupRef({
  configuration: {
    payload: {ui: {ic: {product_group_ref: "product-group:day"}}},
  },
}), "product-group:day");
assert.equal(
  window.FTICResults.factorSeriesPath("factor:v1:roc", "product-group:night"),
  "/factor-series?factor_ref=factor%3Av1%3Aroc&group_ref=product-group%3Anight",
);
console.log("ok");
