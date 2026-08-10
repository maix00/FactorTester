const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-result-model.js",
});

const payloads = {
  equity_curve_data: {
    artifact_kind: "equity_curve",
    series: [
      {label: "A1", currency: "CNY", timestamps: [1, 2], values: [100, 110]},
      {label: "A2", currency: "CNY", timestamps: [1, 2], values: [100, 90]},
    ],
  },
  returns_over_time_data: {
    artifact_kind: "returns_over_time",
    series: [{label: "A1", timestamps: [1, 2], values: [0, 0.1]}],
  },
  metrics_over_time_data: {rows: [
    {series: "A1", timestamp: 1, cumulative_return: 0, max_drawdown: 0},
    {series: "A1", timestamp: 2, cumulative_return: 0.1, annual_return: 0.2,
      sharpe_ratio: 1.4, max_drawdown: -0.05},
  ]},
  fee_detail_data: {rows: [
    {strategy: "A1", product: "CU.SHF", fee: 2},
    {strategy: "A2", product: "AL.SHF", fee: 3},
  ]},
  margin_detail_data: {rows: [{strategy: "A1", margin: 20}]},
  ratio_detail_data: {rows: [{series: "__aggregate__", fee_total: 5}]},
};

const model = window.FTBacktestResultModel.build(payloads);
assert.deepEqual(model.groups, ["A1", "A2"]);
assert.deepEqual(model.tabs, [
  "summary", "equity", "returns", "metrics", "fees", "margin", "ratios",
]);
assert.equal(model.summaryRows[0].total_return, 0.1);
assert.equal(model.summaryRows[0].annual_return, 0.2);
assert.equal(model.summaryRows[0].max_drawdown, -0.05);
assert.ok(Math.abs(model.summaryRows[1].total_return + 0.1) < 1e-12);
assert.deepEqual(
  window.FTBacktestResultModel.scopedRows(payloads.fee_detail_data, "A2"),
  [{strategy: "A2", product: "AL.SHF", fee: 3}],
);
assert.deepEqual(
  window.FTBacktestResultModel.scopedRows(payloads.ratio_detail_data, "A1"),
  payloads.ratio_detail_data.rows,
  "aggregate rows remain visible when a group has no scoped rows",
);

const retainedSummary = {
  initial_capital: 1000000,
  base_currency: "CNY",
  groups: [
    {key: "A1", name: "第一组", metrics_key: "A1"},
    {key: "A2", name: "第二组", metrics_key: "A2"},
  ],
  metrics: {
    A1: {"Total Return": 8, "Annual Return": 16, "Sharpe Ratio": 1.2,
      "Max Drawdown": 4},
    A2: {"Total Return": -2, "Annual Return": -4, "Sharpe Ratio": -0.4,
      "Max Drawdown": 9},
  },
};
const retained = window.FTBacktestResultModel.build({}, retainedSummary);
assert.deepEqual(retained.groups, ["第一组", "第二组"]);
assert.deepEqual(retained.tabs, ["summary", "group_metrics"]);
assert.equal(retained.summaryRows[0].initial_equity, 1000000);
assert.equal(retained.summaryRows[0].total_return, 0.08);
assert.equal(retained.summaryRows[0].max_drawdown, -0.04);
assert.equal(window.FTBacktestResultModel.bestMetricIndex(
  retained.metricMatrix, "Total Return",
), 0);
assert.equal(window.FTBacktestResultModel.bestMetricIndex(
  retained.metricMatrix, "Max Drawdown",
), 0);
console.log("ok");
