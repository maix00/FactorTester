const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
let actionLoaded = false;
const lazyGroups = [];
global.window.FTStaticLoader = {
  async loadGroups(names) {
    lazyGroups.push(...names);
    if (names.includes("workbench-run-batch-actions") && !actionLoaded) {
      vm.runInThisContext(fs.readFileSync(
        "server/manager/web/workbench/run-batch/actions.js", "utf8",
      ), {filename: "run-batch/actions.js"});
      actionLoaded = true;
    }
  },
};
global.FTTestProducts = {
  selectedGroups: state => state.groups,
  groupID: group => group.id,
  groupLabel: group => group.label,
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-lazy-code.js", "utf8",
), {filename: "test-lazy-code.js"});
let revision = 0;
global.FTTestConfiguration = {
  async save(_context, state, group) {
    revision += 1;
    state.workspace = state.workspace || {workspace_id: "workspace-one"};
    return {revision, group_id: group.id};
  },
};
global.FTReferencePage = {
  routeFor: (kind, target) => `/reference?kind=${kind}&target=${target}`,
};
global.FTTestInputState = {
  requestBody: state => ({
    transient_factor_sources: state.transientFactorSources || [],
    transient_strategy_sources: state.transientStrategySources || [],
    strategy_specs: state.strategySpecs || [],
  }),
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-run-fields.js", "utf8",
), {filename: "test-run-fields.js"});
global.FTTestRunFields = window.FTTestRunFields;

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/run-batch/model.js", "utf8",
), {filename: "run-batch/model.js"});

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-run-batch.js", "utf8",
), {filename: "test-run-batch.js"});

const requests = [];
let navigated = false;
const context = {
  t: value => value,
  servicePath: path => `/service${path}`,
  navigate: () => { navigated = true; },
  async api(path, options) {
    requests.push({path, body: JSON.parse(options.body)});
    const index = requests.filter(item => item.path.endsWith("/api/runs")).length;
    if (path.endsWith("/preview")) {
      return {run_spec_hash: `${"a".repeat(63)}${requests.length}`};
    }
    return {
      port: 8141,
      run: {run_id: `run-${index}`, run_spec_hash: `${"b".repeat(63)}${index}`},
      jobs: [{job_id: `job-${index}`}],
    };
  },
};
const state = {
  kind: "ic",
  workspace: {workspace_id: "workspace-one"},
  groups: [
    {id: "day", label: "日盘"},
    {id: "night", label: "夜盘"},
  ],
  outputRequests: ["ic_series", "ic_statistics"],
  manifest: {run_fields: [
    {
      key: "retention_mode", default: "summary", request_location: "body",
      placement: "run_options", order: 10,
    },
    {
      key: "output_requests", default: [], request_location: "body",
      placement: "outputs", order: 20,
    },
  ]},
  runValues: {retention_mode: "full"},
  transientFactorSources: [{
    factor_id: "UploadedMomentum",
    path: "custom_factors/UploadedMomentum.py",
    source_code: "class UploadedMomentum: pass\n",
  }],
  transientStrategySources: [],
  strategySpecs: [],
};

const backtest = {
  ...state,
  kind: "backtest",
  groups: [{id: "all", label: "全部产品"}],
  outputRequests: ["equity_curve"],
  runValues: {retention_mode: "summary"},
  transientFactorSources: [],
  transientStrategySources: [{
    path: "strategies/dynamic_hold.py",
    source_code: "class DynamicHold: pass\n",
  }],
  strategySpecs: [{
    strategy_id: "DynamicHold",
    source: "profile:strategies/dynamic_hold.py",
  }],
};

(async () => {
  const batch = window.FTTestRunBatch;
  assert.equal(actionLoaded, false, "submission code must not load with the batch view");
  assert.deepEqual(batch.synchronize(state).map(item => item.groupID), ["day", "night"]);
  assert.equal(state.activeRunGroupID, "day");
  await batch.previewAll(context, state, () => {});
  assert.deepEqual(state.testRunBatch.map(item => item.phase), ["frozen", "frozen"]);
  assert.ok(state.testRunBatch.every(item => item.runSpecHash.length === 64));

  await batch.runAll(context, state, () => {});
  assert.deepEqual(state.testRunBatch.map(item => item.jobID), ["job-1", "job-2"]);
  assert.equal(state.activeRunGroupID, "night");
  assert.deepEqual(state.testRunBatch.map(item => item.port), [8141, 8141]);
  assert.equal(batch.jobPath(state.testRunBatch[0]), "/jobs/8141/job-1");
  assert.match(batch.runSpecPath(state.testRunBatch[0]), /^\/reference\?kind=run-spec/);

  assert.deepEqual(batch.synchronize(backtest).map(item => item.groupID), ["all"]);
  await batch.runAll(context, backtest, () => {});
  assert.equal(backtest.testRunBatch[0].jobID, "job-3");
  assert.equal(batch.jobPath(backtest.testRunBatch[0]), "/jobs/8141/job-3");
  assert.equal(requests.at(-1).body.analyses[0], "backtest");
  assert.equal(requests.at(-1).body.retention_mode, "summary");
  assert.deepEqual(requests.at(-1).body.output_requests, ["equity_curve"]);
  assert.equal(requests.at(-1).body.transient_strategy_sources[0].path,
    "strategies/dynamic_hold.py");
  assert.equal(requests.at(-1).body.strategy_specs[0].strategy_id, "DynamicHold");
  assert.equal(requests[0].body.transient_factor_sources[0].factor_id,
    "UploadedMomentum");
  assert.equal(navigated, false, "submission must keep the test page visible");
  assert.equal(requests.filter(item => item.path.endsWith("/api/runs")).length, 3);
  assert.equal(actionLoaded, true, "the first explicit action loads submission code");
  assert.ok(lazyGroups.includes("workbench-run-batch-actions"));
  assert.ok(requests.slice(0, 4).every(item => item.body.retention_mode === "full"));
  assert.ok(requests.slice(0, 4).every(item => (
    JSON.stringify(item.body.output_requests) === JSON.stringify(["ic_series", "ic_statistics"])
  )));
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
