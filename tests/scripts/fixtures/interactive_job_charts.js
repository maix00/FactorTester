const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

process.env.TZ = "Asia/Taipei";

(async () => {
global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/jobs/list-format.js", "utf8",
), {filename: "list-format.js"});
global.FTJobListFormat = window.FTJobListFormat;
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/jobs/highcharts-timeline.js", "utf8",
), {filename: "highcharts-timeline.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/core/highcharts-range-loader.js", "utf8",
), {filename: "highcharts-range-loader.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/jobs/highcharts-viewers.js", "utf8",
), {filename: "highcharts-viewers.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/jobs/artifacts.js", "utf8",
), {filename: "artifacts.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/jobs/job-artifact-viewers.js", "utf8",
), {filename: "job-artifact-viewers.js"});

const context = {t: value => value};
const equity = window.FTJobHighcharts.optionsFor("equity_curve", {
  artifact_kind: "equity_curve",
  series: [{
    label: "A1", currency: "CNY",
    timestamps: ["2025-01-03T15:00:00+08:00", "2025-01-06T09:00:00+08:00"],
    values: [1_000_000, 1_020_000], drawdown: [0, -0.01],
  }, {
    label: "A2", currency: "CNY",
    timestamps: ["2025-01-03T15:00:00+08:00", "2025-01-06T10:00:00+08:00"],
    values: [1_000_000, 990_000], drawdown: [0, -0.02],
  }],
}, context);
assert.equal(equity.series[0].name, "A1");
assert.equal(equity.series.length, 2, "the equity chart must not embed drawdown series");
assert.equal(equity.time.timezone, "Asia/Taipei", "timestamps must render in the user's browser timezone");
assert.equal(equity.navigator.enabled, true);
assert.equal(equity.rangeSelector.allButtonsEnabled, true);
assert.equal(equity.scrollbar.enabled, true);
assert.equal(equity.yAxis[0].title.text, "金额（CNY）");
assert.equal(equity.xAxis.ordinal, true, "non-trading gaps must be compressed");
assert.deepEqual(equity.xAxis, window.FTChartTimeline.observedTimeAxis());
assert.equal(equity.yAxis.length, 2, "equity keeps only amount and cumulative-return axes");
assert.equal(equity.yAxis[1].linkedTo, 0);
const drawdown = window.FTJobHighcharts.optionsFor("drawdown_curve", {
  artifact_kind: "equity_curve",
  series: [{
    label: "A1", currency: "CNY", timestamps: ["2025-01-02", "2025-01-03"],
    values: [1_000_000, 990_000], drawdown: [0, -0.01],
  }],
}, context);
assert.equal(drawdown.series.length, 1);
assert.equal(drawdown.series[0].name, "A1 · 当前回撤");
assert.equal(drawdown.series[0].data[1][1], -1);
assert.equal(drawdown.yAxis.length, 1);
assert.equal(drawdown.yAxis[0].max, 0);
assert.ok(Number.isFinite(equity.series[0].data[0][0]));
assert.equal(
  window.FTChartTimeline.timestamp("2025-01-02"),
  new Date(2025, 0, 2, 0, 0, 0, 0).getTime(),
  "date-only observations must mean midnight in the user's timezone",
);
assert.equal(
  window.FTChartTimeline.timestamp("2025-03-09T01:30:00-05:00"),
  Date.parse("2025-03-09T01:30:00-05:00"),
  "timestamps with an explicit offset must preserve their absolute instant",
);
const observedTimes = new Set(equity.series.flatMap(item => item.data.map(point => point[0])));
assert.equal(observedTimes.size, 3, "the adapter must not synthesize non-trading timestamps");

let requestedRange = null;
let replacedData = null;
const progressive = window.FTJobHighcharts.optionsFor("equity_curve", {
  artifact_kind: "equity_curve",
  series: [{label: "A1", timestamps: [1, 2], values: [100, 101]}],
}, context, "", {
  rangeDebounceMs: 1,
  async loadRange(min, max, options) {
    requestedRange = {min, max, maxPoints: options.maxPoints};
    return {
      artifact_kind: "equity_curve",
      series: [{
        label: "A1",
        timestamps: [1_700_000_000_000, 1_700_000_001_000],
        values: [110, 111],
      }],
    };
  },
  rangeOptions(payload) {
    return window.FTJobHighcharts.optionsFor("equity_curve", payload, context);
  },
});
const progressiveSeries = {
  name: "A1", options: {},
  update() {}, setData(data) { replacedData = data; }, remove() {},
};
const progressiveChart = {
  series: [progressiveSeries], plotWidth: 400,
  xAxis: [{setExtremes() {}}],
  showLoading() {}, hideLoading() {}, redraw() {}, addSeries() {},
};
progressive.xAxis.events.afterSetExtremes.call(
  {chart: progressiveChart}, {
    min: 10, max: 11, dataMin: 1_690_000_000_000,
    dataMax: 1_710_000_000_000, trigger: "navigator",
  },
);
await new Promise(resolve => setTimeout(resolve, 20));
assert.deepEqual(requestedRange, {min: 10, max: 11, maxPoints: 600});
assert.deepEqual(replacedData, [
  [1_690_000_000_000, null],
  [1_700_000_000_000, 110], [1_700_000_001_000, 111],
  [1_710_000_000_000, null],
]);
assert.equal(progressive.chart.zooming.mouseWheel.showResetButton, true);
requestedRange = {stale: true};
progressive.xAxis.events.afterSetExtremes.call(
  {chart: progressiveChart}, {
    min: 10, max: 11, trigger: "rangeSelectorButton",
    rangeSelectorButton: {type: "all"},
  },
);
await new Promise(resolve => setTimeout(resolve, 20));
assert.deepEqual(requestedRange, {min: undefined, max: undefined, maxPoints: 600});

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
  "metrics_chart", metrics, context, "sharpe_ratio", {hideTitle: true},
);
assert.equal(metricChart.series[0].name, "A1 · Sharpe ratio");
assert.equal(metricChart.yAxis[0].title.text, "Sharpe ratio");
assert.equal(metricChart.title.text, null, "the result card owns the only visible chart title");
assert.equal(metricChart.series[0].data.length, 2, "missing metrics must not render as zero");

const marginChart = window.FTJobHighcharts.rowSeriesOptions({rows: [
  {strategy: "A1", timestamp: "2025-01-02", product: "A", margin: 10, equity: 100,
    margin_utilization: 0.1},
  {strategy: "A1", timestamp: "2025-01-02", product: "B", margin: 10, equity: 100,
    margin_utilization: 0.1},
  {strategy: "A1", timestamp: "2025-01-02", product: "C", margin: 10, equity: 100,
    margin_utilization: 0.1},
]}, context, {
  label: "保证金占用率", fields: ["margin_utilization"],
  labels: {margin_utilization: "保证金占用率"}, percentFields: ["margin_utilization"],
  aggregate: "strategy_margin_equity_ratio",
});
assert.equal(marginChart.series.length, 1);
assert.deepEqual(marginChart.series[0].data.map(point => point[1]), [30],
  "product-level margin rows must render the strategy total utilization");
const marginWithTotal = window.FTJobHighcharts.rowSeriesOptions({rows: [
  {strategy: "A1", timestamp: "2025-01-02", product: "__total__", margin: 30,
    equity: 100, margin_utilization: 0.3},
  {strategy: "A1", timestamp: "2025-01-02", product: "A", margin: 10,
    equity: 100, margin_utilization: 0.1},
]}, context, {
  label: "保证金占用率", fields: ["margin_utilization"],
  labels: {margin_utilization: "保证金占用率"}, percentFields: ["margin_utilization"],
  aggregate: "strategy_margin_equity_ratio",
});
assert.deepEqual(marginWithTotal.series[0].data.map(point => point[1]), [30],
  "an authoritative total row must not be added to product rows again");

const splitMs = Date.parse("2025-01-03T00:00:00Z");
const inSample = window.FTJobHighcharts.optionsFor(
  "equity_curve", {
    artifact_kind: "equity_curve",
    series: [{label: "A1", timestamps: ["2025-01-02", "2025-01-04"], values: [1, 2]}],
  }, context, "", {splitMs, showOutOfSample: false},
);
assert.equal(inSample.xAxis.max, splitMs);
assert.deepEqual(inSample.xAxis.plotBands, []);
const fullSample = window.FTJobHighcharts.optionsFor(
  "equity_curve", {
    artifact_kind: "equity_curve",
    series: [{label: "A1", timestamps: ["2025-01-02", "2025-01-04"], values: [1, 2]}],
  }, context, "", {splitMs, showOutOfSample: true},
);
assert.equal(fullSample.xAxis.max, null);
assert.equal(fullSample.xAxis.plotBands[0].from, splitMs);
assert.equal(fullSample.xAxis.plotBands[0].label.text, "样本外");

const picked = window.FTJobArtifacts.declarationArtifact({
  name: "equity_curve", presentation: "chart", viewer: "equity_curve",
  artifacts: ["equity_curve_report", "equity_curve_data"],
}, [
  {name: "equity_curve_report", content_type: "image/svg+xml"},
  {name: "equity_curve_data", content_type: "application/json"},
]);
assert.equal(picked.name, "equity_curve_data");
assert.equal(window.FTJobHighcharts.supports({name: "equity_curve"}), true);
assert.equal(window.FTJobHighcharts.supports({name: "returns_over_time"}), true);
assert.equal(window.FTJobHighcharts.supports({name: "metrics_over_time"}), true);
assert.equal(window.FTJobHighcharts.supports({name: "ic_series", viewer: "line_chart"}), false);
assert.equal(window.FTJobHighcharts.supports({viewer: "equity_curve"}), false);

const staticIC = window.FTJobArtifacts.declarationArtifact({
  name: "ic_series", presentation: "chart", viewer: "line_chart",
  artifacts: ["ic_series_report", "ic_series_data"],
}, [
  {name: "ic_series_report", content_type: "image/svg+xml"},
  {name: "ic_series_data", content_type: "application/json"},
]);
assert.equal(staticIC.name, "ic_series_report");

const legacyFilenameDeclaration = window.FTJobArtifacts.declarationArtifact({
  name: "ic_series", presentation: "chart", viewer: "line_chart",
  artifacts: ["ic_series_report.svg", "ic_series_data.json"],
}, [
  {name: "ic_series_report", file_name: "ic_series_report.svg", content_type: "image/svg+xml"},
  {name: "ic_series_data", file_name: "ic_series_data.json", content_type: "application/json"},
]);
assert.equal(
  legacyFilenameDeclaration.name,
  "ic_series_report",
  "file_name declarations must resolve to the canonical artifact name",
);

const oldEquityWithoutData = window.FTJobArtifacts.declarationArtifact({
  name: "equity_curve", presentation: "chart", viewer: "equity_curve",
  artifacts: ["equity_curve_report", "equity_curve_data", "equity_curve_receipt"],
}, [
  {name: "equity_curve_report", content_type: "image/svg+xml"},
  {name: "equity_curve_receipt", content_type: "application/json"},
]);
assert.equal(oldEquityWithoutData.name, "equity_curve_report");

const equityCandidates = window.FTJobArtifacts.declarationArtifacts({
  name: "equity_curve", presentation: "chart", viewer: "equity_curve",
  artifacts: ["equity_curve_report", "equity_curve_data"],
}, [
  {name: "equity_curve_report", content_type: "image/svg+xml"},
  {name: "equity_curve_data", content_type: "application/json"},
]);
assert.deepEqual(
  equityCandidates.map(item => item.name),
  ["equity_curve_data", "equity_curve_report"],
);
assert.deepEqual(window.FTJobArtifacts.artifactDownloadParts({
  role: "input", artifact_kind: "run_dependency",
  file_name: "settings.yaml", logical_path: "strategies/a/settings.yaml",
}), ["inputs", "run_dependency", "strategies", "a", "settings.yaml"]);
assert.deepEqual(window.FTJobArtifacts.artifactDownloadParts({
  role: "input", artifact_kind: "run_dependency",
  file_name: "settings.yaml", logical_path: "../outside/settings.yaml",
}), ["inputs", "run_dependency", "settings.yaml"]);
assert.deepEqual(window.FTJobArtifacts.artifactDownloadParts({
  role: "output", file_name: "equity_curve.svg",
}), ["equity_curve.svg"]);

function fakeElement() {
  return {
    open: false, children: [], listeners: {}, textContent: "",
    append(...items) { this.children.push(...items); },
    addEventListener(name, callback) { this.listeners[name] = callback; },
    replaceChildren(...items) { this.children = items; },
  };
}
global.document = {createElement: fakeElement};
const analyzingStatus = window.FTJobListFormat.statusCell({
  status: "succeeded", supplemental_active_count: 1,
}, context);
assert.equal(analyzingStatus.textContent, "分析中");
const completedStatus = window.FTJobListFormat.statusCell({
  status: "succeeded", supplemental_active_count: 0,
  supplemental_failed_count: 3,
}, context);
assert.equal(
  completedStatus.textContent, "成功",
  "supplemental failures belong in Job detail and must not complicate list status",
);
const previewAttempts = [];
global.FTJobArtifactViewers = {
  async mount(_context, _target, options) {
    previewAttempts.push(options.artifact.name);
    if (previewAttempts.length === 1) {
      const error = new Error("HTTP 404"); error.status = 404; throw error;
    }
  },
};
const fallbackPreview = window.FTJobArtifacts.lazyArtifactPreview(
  context, {name: "equity_curve", label: "Equity"}, equityCandidates,
  "job-1", "?port=8141",
);
fallbackPreview.open = true;
await fallbackPreview.listeners.toggle();
assert.deepEqual(previewAttempts, ["equity_curve_data", "equity_curve_report"]);

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
})();
