const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {
  FTBacktestResultModel: {
    payloadNames: [
      "equity_curve_data", "returns_over_time_data", "metrics_over_time_data",
      "fee_detail_data", "margin_detail_data", "ratio_detail_data",
    ],
    groupEquityEntries: summary => (summary?.groups || []).filter(item => (
      Array.isArray(item.timestamps) && Array.isArray(item.total_equity)
        && item.timestamps.length && item.total_equity.length
    )),
  },
};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-result-view.js",
});

const artifacts = [
  {name: "equity_curve_data", state: "active"},
  {name: "group_equity_data", state: "active"},
  {name: "fee_detail_data", state: "superseded"},
  {name: "ic_series_data", state: "active"},
];
assert.equal(window.FTBacktestResults.supports(artifacts), true);
assert.deepEqual(
  window.FTBacktestResults.relevantArtifacts(artifacts).map(item => item.name),
  ["equity_curve_data"],
);
assert.equal(window.FTBacktestResults.supports([
  {name: "ic_series_data", state: "active"},
]), false);
assert.equal(window.FTBacktestResults.supports([], {
  metrics: {A1: {"Total Return": 3}},
}), true, "retained Job summary is a domain result even without artifacts");
assert.equal(window.FTBacktestResults.supports([], {
  groups: [{timestamps: [1], total_equity: [100]}],
}), true, "retained strategy equity is a domain result without chart artifacts");
console.log("ok");
