const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "ic-result-model.js",
});

const model = window.FTICResultModel.build({
  ic_series_data: {series: [
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", horizon: "MIN1", dates: [1, 2, 3, 4], values: [0.1, 0.2, 0.1, 0.3]},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", horizon: "DAY1", dates: [1, 2, 3, 4], values: [0.03, 0.04, 0.02, 0.05]},
    {factor_alias: "SgCCS", factor_ref: "factor:v1:sg", horizon: "MIN1", dates: [1, 2, 3, 4], values: [0.2, 0.1, 0.3, 0.2]},
  ]},
  ic_statistics_data: {rows: [
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", forward_return_horizon: "DAY1", mean_ic: 0.04, std_ic: 0.2, icir_signal: 0.2},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", forward_return_horizon: "MIN1", mean_ic: 0.08, std_ic: 0.1, icir_signal: 0.8},
    {factor_alias: "SgCCS", factor_ref: "factor:v1:sg", forward_return_horizon: "MIN1", mean_ic: 0.06, std_ic: 0.12, icir_signal: 0.5},
  ]},
  ic_statistics_summary_data: {rows: [
    {
      factor: "[ROC](factortester://factor/factor%3Av1%3Aroc)",
      entry_delay_bars: 0, primary_forward_return_horizon: "DAY1",
    },
    {
      factor: "[SgCCS](factortester://factor/factor%3Av1%3Asg)",
      entry_delay_bars: 0, primary_forward_return_horizon: "MIN1",
    },
  ]},
  ic_rolling_stability_data: {rows: [{factor_alias: "ROC", window_key: "signals:K=60"}]},
  ic_period_diagnostics_data: {rows: [{factor_alias: "ROC", period_label: "month"}]},
});

assert.equal(model.factors.length, 2);
assert.deepEqual(model.factors.map(item => item.factorAlias), ["ROC", "SgCCS"]);
const mean = model.matrix.metrics.find(item => item.key === "mean_ic");
const std = model.matrix.metrics.find(item => item.key === "std_ic");
assert.deepEqual(mean.values, [0.04, 0.06]);
assert.equal(mean.bestIndex, 1);
assert.equal(std.bestIndex, 1);
assert.equal(window.FTICResultModel.primarySeries(model.factors[0], model.summaryRows).horizon, "DAY1");
assert.deepEqual(
  window.FTICResultModel.decay(model.factors[0]).map(item => item.horizon),
  ["MIN1", "DAY1"],
);
assert.equal(window.FTICResultModel.autocorrelation(model.factors[0]).length, 2);
assert.equal(
  window.FTICResultModel.histogram(model.factors[0]).reduce((sum, item) => sum + item.count, 0),
  4,
);
assert.equal(model.rollingRows.length, 1);
assert.equal(model.periodRows.length, 1);
console.log("ok");
