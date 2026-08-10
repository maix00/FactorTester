const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/jobs/highcharts-viewers.js", "utf8",
), {filename: "highcharts-viewers.js"});
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/jobs/artifacts.js", "utf8",
), {filename: "artifacts.js"});
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/jobs/job-artifact-viewers.js", "utf8",
), {filename: "job-artifact-viewers.js"});

const context = {t: value => value};
const equity = window.FTJobHighcharts.optionsFor("equity_curve", {
  artifact_kind: "equity_curve",
  series: [{
    label: "A1", currency: "CNY",
    timestamps: ["2025-01-02T15:00:00+08:00", "2025-01-03T15:00:00+08:00"],
    values: [1_000_000, 1_020_000], drawdown: [0, -0.01],
  }],
}, context);
assert.equal(equity.series[0].name, "A1");
assert.equal(equity.series[1].name, "A1 · 当前回撤");
assert.equal(equity.series[1].yAxis, 1);
assert.equal(equity.navigator.enabled, true);
assert.equal(equity.scrollbar.enabled, true);
assert.equal(equity.yAxis[0].title.text, "金额（CNY）");
assert.ok(Number.isFinite(equity.series[0].data[0][0]));

const ic = window.FTJobHighcharts.optionsFor("line_chart", {
  artifact_kind: "ic_series",
  series: [{label: "ROC", timestamps: [1, 2], values: [0.1, -0.2]}],
}, context);
assert.equal(ic.yAxis[0].plotLines[0].value, 0);
assert.equal(ic.yAxis[0].title.text, "IC");

const metrics = {
  artifact_kind: "metrics_over_time",
  rows: [
    {series: "A1", timestamp: "2025-01-02", annual_return: 0.1, sharpe_ratio: 1.2},
    {series: "A1", timestamp: "2025-01-03", annual_return: 0.2, sharpe_ratio: 1.3},
    {series: "A1", timestamp: "2025-01-04", annual_return: null, sharpe_ratio: null},
  ],
};
assert.deepEqual(
  window.FTJobHighcharts.metricChoices(metrics).map(item => item.key),
  ["annual_return", "sharpe_ratio"],
);
const metricChart = window.FTJobHighcharts.optionsFor(
  "metrics_chart", metrics, context, "sharpe_ratio",
);
assert.equal(metricChart.series[0].name, "A1 · Sharpe ratio");
assert.equal(metricChart.yAxis[0].title.text, "Sharpe ratio");
assert.equal(metricChart.series[0].data.length, 2, "missing metrics must not render as zero");

const picked = window.FTJobArtifacts.declarationArtifact({
  presentation: "chart", viewer: "equity_curve",
  artifacts: ["equity_curve_report", "equity_curve_data"],
}, [
  {name: "equity_curve_report", content_type: "image/svg+xml"},
  {name: "equity_curve_data", content_type: "application/json"},
]);
assert.equal(picked.name, "equity_curve_data");

const records = window.FTJobArtifactViewers.tableModel({
  columns: ["factor_alias", "mean_ic"],
  column_presentations: {
    factor_alias: {
      presentation: "reference", kind: "factor", target_ref_field: "factor_ref",
    },
  },
  rows: [{factor_alias: "ROC", factor_ref: "factor:v1:frozen", mean_ic: 0.12}],
});
assert.deepEqual(records.columns, ["factor_alias", "mean_ic"]);
assert.equal(records.rows[0].mean_ic, 0.12);
assert.equal(records.presentations.factor_alias.kind, "factor");

const matrix = window.FTJobArtifactViewers.tableModel({
  columns: ["factor", "ic"], rows: [["ROC", 0.1], ["SgCCS", 0.2]],
});
assert.deepEqual(matrix.rows, [
  {factor: "ROC", ic: 0.1}, {factor: "SgCCS", ic: 0.2},
]);
assert.equal(
  window.FTJobArtifactViewers.referenceURL("factor", "factor:v1:frozen"),
  "factortester://factor/factor%3Av1%3Afrozen",
);
console.log("ok");
