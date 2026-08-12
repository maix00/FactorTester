const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "ic-result-model.js",
});

const model = window.FTICResultModel.build({
  ic_series_data: {series: [
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "rank", horizon: "MIN1", entry_delay_bars: 0, dates: [1, 2, 3, 4], values: [0.1, 0.2, 0.1, 0.3]},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "rank", horizon: "DAY1", entry_delay_bars: 0, dates: [1, 2, 3, 4], values: [0.03, 0.04, 0.02, 0.05]},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "rank", horizon: "MIN1", entry_delay_bars: 1, dates: [1, 2, 3, 4], values: [0.05, 0.04, 0.03, 0.02]},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "pearson", horizon: "MIN1", entry_delay_bars: 0, dates: [1, 2, 3, 4], values: [0.4, 0.3, 0.2, 0.1]},
    {factor_alias: "SgCCS", factor_ref: "factor:v1:sg", ic_method: "rank", horizon: "MIN1", entry_delay_bars: 0, dates: [1, 2, 3, 4], values: [0.2, 0.1, 0.3, 0.2]},
  ]},
  ic_statistics_data: {rows: [
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "rank", forward_return_horizon: "DAY1", entry_delay_bars: 0, mean_ic: 0.04, std_ic: 0.2, icir_signal: 0.2},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "rank", forward_return_horizon: "MIN1", entry_delay_bars: 0, mean_ic: 0.08, std_ic: 0.1, icir_signal: 0.8},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "rank", forward_return_horizon: "MIN1", entry_delay_bars: 1, mean_ic: 0.03, std_ic: 0.1, icir_signal: 0.3},
    {factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "pearson", forward_return_horizon: "MIN1", entry_delay_bars: 0, mean_ic: 0.02, std_ic: 0.2, icir_signal: 0.1},
    {factor_alias: "SgCCS", factor_ref: "factor:v1:sg", ic_method: "rank", forward_return_horizon: "MIN1", entry_delay_bars: 0, mean_ic: 0.06, std_ic: 0.12, icir_signal: 0.5},
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
  ic_rolling_stability_data: {rows: [{factor_alias: "ROC", ic_method: "rank", forward_return_horizon: "MIN1", entry_delay_bars: 0, window_key: "signals:K=60"}]},
  ic_period_diagnostics_data: {rows: [{factor_alias: "ROC", ic_method: "rank", forward_return_horizon: "MIN1", entry_delay_bars: 0, period_label: "month"}]},
  ic_holding_half_life_data: {rows: [{
    factor_alias: "ROC", factor_ref: "factor:v1:roc",
    entry_delay_bars: 0, exponential_half_life_seconds: 120,
  }]},
  ic_quantile_portfolio_statistics_data: {rows: [{
    factor_alias: "ROC", factor_ref: "factor:v1:roc", ic_method: "rank",
    forward_return_horizon: "DAY1", entry_delay_bars: 0,
    portfolio_mode: "no_fee", portfolio_kind: "group", group_index: 0,
    total_return: 0.1, avg_turnover: 0.2,
  }]},
});

assert.equal(model.factors.length, 2);
assert.deepEqual(model.factors.map(item => item.factorAlias), ["ROC", "SgCCS"]);
assert.deepEqual(model.methods, ["rank", "pearson"]);
assert.deepEqual(model.descriptors, [
  {horizon: "MIN1", delay: 0},
  {horizon: "MIN1", delay: 1},
  {horizon: "DAY1", delay: 0},
]);
const mean = model.matrix.metrics.find(item => item.key === "mean_ic");
const std = model.matrix.metrics.find(item => item.key === "std_ic");
assert.deepEqual(mean.values, [0.04, 0.06]);
assert.equal(mean.bestIndex, 1);
assert.equal(std.bestIndex, 1);
assert.equal(window.FTICResultModel.primarySeries(model.factors[0], model.summaryRows).horizon, "DAY1");
assert.equal(window.FTICResultModel.seriesFor(
  model.factors[0], {horizon: "MIN1", delay: 1}, "rank",
).delay, 1);
const rankMin1 = window.FTICResultModel.statisticMatrix(
  model.factors, model.summaryRows, {horizon: "MIN1", delay: 0}, "rank",
);
assert.deepEqual(rankMin1.metrics.find(item => item.key === "mean_ic").values, [0.08, 0.06]);
const pearsonMin1 = window.FTICResultModel.statisticMatrix(
  model.factors, model.summaryRows, {horizon: "MIN1", delay: 0}, "pearson",
);
assert.deepEqual(pearsonMin1.metrics.find(item => item.key === "mean_ic").values, [0.02, null]);
assert.deepEqual(
  window.FTICResultModel.decay(model.factors[0], "rank").map(item => `${item.horizon}:d${item.delay}`),
  ["MIN1:d0", "MIN1:d1", "DAY1:d0"],
);
assert.equal(window.FTICResultModel.autocorrelation(
  model.factors[0], 20, model.summaryRows, {horizon: "MIN1", delay: 1}, "rank",
).length, 2);
assert.equal(
  window.FTICResultModel.histogram(model.factors[0]).reduce((sum, item) => sum + item.count, 0),
  4,
);
assert.equal(model.rollingRows.length, 1);
assert.equal(model.periodRows.length, 1);
assert.equal(model.halfLifeRows.length, 1);
assert.equal(model.halfLifeRows[0].exponential_half_life_seconds, 120);
assert.equal(model.portfolioRows.length, 1);
assert.equal(model.factors[0].portfolio.length, 1);
assert.equal(window.FTICResultModel.portfolioRowsFor(
  model.factors[0], {horizon: "DAY1", delay: 0}, "rank",
).length, 1);
console.log("ok");
