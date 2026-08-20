const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const removed = [];
global.localStorage = {removeItem: key => removed.push(key)};
global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-state.js", "utf8"),
  {filename: "test-state.js"},
);

const state = {
  kind: "backtest",
  manifest: {run_fields: [
    {key: "retention_mode", placement: "submission", default: "summary"},
  ]},
  workspace: {workspace_id: "saved"},
  analysis: {groups: [{id: "group-1"}]},
  savedFactors: [{factor_ref: "factor-1"}],
  savedTemporaryObjects: {factors: [{factor_ref: "factor-1"}]},
  factorRef: "factor-1", groupRef: "products-1", groupRefs: ["products-1"],
  values: {factor_candidates: [{factor_ref: "factor-1"}]},
  settingsInitialized: true, settingsMountedTabs: ["factor"], settingsTabKey: "factor",
  transientFactorSources: [{factor_id: "factor-1"}],
  transientFactorFamilies: [{family: "Family"}],
  transientStrategySources: [{path: "strategy.py"}],
  strategySpecs: [{id: "strategy"}], strategyInspections: [{id: "inspection"}],
  runInputDependencies: [{path: "input.csv"}],
  outputRequests: ["equity_curve"], outputRequestsExplicit: true,
  testRunBatch: [{groupID: "backtest"}], activeRunGroupID: "backtest",
  selectedBacktestGroupIDs: ["group-1"], selectedBacktestLongShortIDs: ["ls-1"],
  runValues: {retention_mode: "full"},
};

window.FTTestState.clearDraft(state);
assert.strictEqual(state.workspace, null);
assert.deepStrictEqual(state.analysis, {});
assert.deepStrictEqual(state.transientFactorSources, []);
assert.deepStrictEqual(state.transientFactorFamilies, []);
assert.deepStrictEqual(state.transientStrategySources, []);
assert.deepStrictEqual(state.strategySpecs, []);
assert.deepStrictEqual(state.runInputDependencies, []);
assert.deepStrictEqual(state.testRunBatch, []);
assert.deepStrictEqual(state.runValues, {retention_mode: "summary"});
assert.strictEqual(state.values, null);
assert.strictEqual(state.settingsInitialized, false);
assert.deepStrictEqual(removed, []);

state.analysis = {groups: [{id: "restored"}]};
state.workspace = {workspace_id: "workspace-tab-a"};
state.values = {factor_candidates: [{factor_ref: "factor-restored"}]};
state.settingsMountedTabs = ["factor"];
state.settingsTabKey = "factor";
const snapshot = window.FTTestState.draftSnapshot(state);
state.analysis = {};
state.values = null;
assert.strictEqual(window.FTTestState.restoreDraft(state, snapshot), true);
assert.strictEqual(snapshot.schemaVersion, 2);
assert.strictEqual(snapshot.workspaceID, "workspace-tab-a");
assert.strictEqual(state.restoredWorkspaceID, "workspace-tab-a");
assert.deepStrictEqual(state.analysis, {groups: [{id: "restored"}]});
assert.deepStrictEqual(state.values, {factor_candidates: [{factor_ref: "factor-restored"}]});
assert.strictEqual(state.settingsInitialized, false);
assert.strictEqual(window.FTTestState.restoreDraft(state, {
  schemaVersion: 1, kind: "backtest", values: {},
}), false);
console.log("ok");
