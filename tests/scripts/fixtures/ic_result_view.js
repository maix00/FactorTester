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
  {name: "ic_quantile_portfolio_statistics_data", state: "active"},
  {name: "ic_series_report", state: "active"},
  {name: "ic_rolling_stability_data", state: "deleted"},
];
assert.equal(window.FTICResults.supports(artifacts), false,
  "IC result tabs require the Job's registered projection contract");
assert.deepEqual(
  window.FTICResults.relevantArtifacts(artifacts).map(item => item.name),
  [],
);
assert.equal(window.FTICResults.supports([
  {name: "equity_curve_data", state: "active"},
]), false);
assert.equal(window.FTICResults.supports([
  {name: "ic_quantile_portfolio_statistics_data", state: "active"},
]), false);
const declarations = [{result_tabs: [
  {key: "summary", label: "IC 汇总", order: 10,
    source_artifacts: ["ic_statistics_summary_data"], source_policy: "any"},
  {key: "series", label: "IC 序列", order: 20,
    source_artifacts: ["ic_series_data"], source_policy: "any"},
  {key: "rolling", label: "Rolling IC", order: 30,
    source_artifacts: ["ic_rolling_stability_data"], source_policy: "any"},
]}];
const declaredArtifacts = [
  {name: "ic_series_data", state: "active"},
  {name: "ic_statistics_summary_data", state: "active"},
  {name: "ic_rolling_stability_data", state: "deleted"},
  {name: "ic_statistics_data", state: "active"},
];
assert.deepEqual(
  window.FTICResults.tabsForArtifacts(declarations, declaredArtifacts)
    .map(item => item.key),
  ["summary", "series"],
);
assert.deepEqual(
  window.FTICResults.relevantArtifacts(declaredArtifacts, declarations)
    .map(item => item.name),
  ["ic_series_data", "ic_statistics_summary_data"],
);
assert.equal(window.FTICResults.supports(
  [{name: "ic_statistics_data", state: "active"}], declarations,
), false);
assert.equal(window.FTICResults.productGroupRef({
  payload: {
    analyses: {ic: {configuration_groups: [{
      config_group_id: "icg-night", product_scope_ref: "product-group:night",
    }]}},
  },
}), "product-group:night");
assert.equal(window.FTICResults.productGroupRef({
  payload: {
    analyses: {ic: {configuration_groups: [{config_group_id: "icg-not-a-product"}]}},
  },
}), "", "config_group_id must never be used as a product-group reference");
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
