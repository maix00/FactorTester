const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.FTTestProducts = {
  selectedGroups: state => state.groups || [],
};
global.FTTestFactorSelection = {
  selectedIDs: state => state.selectedFactorIDs || [],
};
window.FTTestFactorSelection = global.FTTestFactorSelection;

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/ic-configuration.js", "utf8",
), {filename: "ic-configuration.js"});
global.FTICConfiguration = window.FTICConfiguration;

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/ic-horizon-settings.js", "utf8",
), {filename: "ic-horizon-settings.js"});
global.FTICHorizonSettings = window.FTICHorizonSettings;

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-run-summary.js", "utf8",
), {filename: "test-run-summary.js"});

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-run-results.js", "utf8",
), {filename: "test-run-results.js"});

const results = window.FTTestRunResults;
const summary = window.FTTestRunSummary;
const explicit = summary.evaluationPlan({
  kind: "ic",
  selectedFactorIDs: ["factor:one", "factor:two"],
  groups: [{id: "day"}, {id: "night"}],
  values: {
    forward_return_horizons: {
      sampling: "explicit", bases: ["signal", "1d"], multipliers: [1, 5],
    },
    ic_lags: [0, 1, 2],
    ic_correlation: "both",
  },
});
assert.deepEqual(explicit, {
  factors: 2, horizons: 4, horizonMode: "explicit", delays: 3,
  methods: 2, jobs: 2, slicesPerJob: 48, exact: false,
});

const automatic = summary.evaluationPlan({
  kind: "ic", selectedFactorIDs: ["factor:one"], groups: [{id: "all"}],
  values: {
    forward_return_horizons: {sampling: "scale_aware"},
    ic_lags: [0], ic_correlation: "rank",
  },
});
assert.equal(automatic.horizons, null);
assert.equal(automatic.slicesPerJob, null);
assert.equal(automatic.horizonMode, "scale_aware");
assert.equal(automatic.exact, false);

const item = {phase: "submitted", port: 0};
results.recordDetail(item, {
  payload: {result_summary: {ok: true}},
  taskDetail: {artifacts: []},
  job: {status: "succeeded"},
  resolvedPort: 8141,
  portQuery: "?port=8141",
});
assert.equal(item.phase, "succeeded");
assert.equal(item.port, 8141);
assert.equal(item.portQuery, "?port=8141");
assert.deepEqual(item.detailPayload.result_summary, {ok: true});

let icOptions = null;
window.FTICResults = {
  section: (_context, options) => { icOptions = options; return options; },
};
results.resultSection({}, {kind: "ic"}, {
  jobID: "job-one", groupID: "product-group:night", portQuery: "?port=8141",
  taskDetail: {
    artifacts: [{name: "ic_statistics_data", state: "active"}],
    configuration: {payload: {analyses: {ic: {product_path_selection_id: "fallback"}}}},
  },
});
assert.equal(icOptions.productGroupRef, "product-group:night");
assert.equal(icOptions.configuration.payload.analyses.ic.product_path_selection_id, "fallback");
console.log("ok");
