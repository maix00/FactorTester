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

const factorRef = `factor:v2:${"a".repeat(43)}`;
vm.runInThisContext(fs.readFileSync("server/manager/web/core/page-state.js", "utf8"));
for (const kind of ["ic", "backtest", "factor_evaluation"]) {
  const durable = {};
  const pageState = window.FTPageState.create({durable});
  const live = {kind, values: {}, factors: [], groups: []};
  window.FTTestState.bindDraftCheckpoint({tabSession:{durable},pageState}, live);
  // Change an inner editor after the parent page's last render.
  live.icConfigurationGroupEditor = {mode:"create",draft:{factor_ref:factorRef}};
  live.backtestGroupEditor = {mode:"group",draft:{factor_candidate_refs:[factorRef]}};
  live.values.category_candidates = [{id:"inline-category",temporary:true}];
  pageState.capture();
  const restored = {kind, factors:[], groups:[]};
  assert.equal(window.FTTestState.restoreDraft(restored, durable.testDrafts[kind]), true);
  assert.deepEqual(restored.icConfigurationGroupEditor, live.icConfigurationGroupEditor);
  assert.deepEqual(restored.backtestGroupEditor, live.backtestGroupEditor);
  assert.deepEqual(restored.values.category_candidates, live.values.category_candidates);
}
const frozenFactor = {
  schema_version: 2, ref: factorRef, alias: "Factor A",
  owner_ref: "owner:alice", identity: {family_ref: "family:a"},
};

const state = {
  kind: "backtest",
  manifest: {run_fields: [
    {key: "retention_mode", placement: "submission", default: "summary"},
  ]},
  workspace: {workspace_id: "saved"},
  analysis: {groups: [{id: "group-1"}]},
  savedFactors: [frozenFactor],
  savedTemporaryObjects: {factors: [frozenFactor]},
  factorRef, groupRef: "products-1", groupRefs: ["products-1"],
  values: {factor_candidates: [frozenFactor]},
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
assert.strictEqual(state.settingsTabKey, null);
assert.strictEqual(state.backtestGroupsOpen, true);
assert.deepStrictEqual(removed, []);

state.analysis = {groups: [{id: "restored", factor_candidate_refs: [factorRef]}]};
state.workspace = {workspace_id: "workspace-tab-a"};
state.savedFactors = [frozenFactor];
state.values = {factor_candidates: [frozenFactor]};
state.settingsMountedTabs = ["factor"];
state.settingsTabKey = "factor";
const snapshot = window.FTTestState.draftSnapshot(state);
state.analysis = {};
state.values = null;
assert.strictEqual(window.FTTestState.restoreDraft(state, snapshot), true);
assert.strictEqual(snapshot.schemaVersion, 2);
assert.strictEqual(snapshot.workspaceID, "workspace-tab-a");
assert.strictEqual(state.restoredWorkspaceID, "workspace-tab-a");
assert.deepStrictEqual(state.analysis, {
  groups: [{id: "restored", factor_candidate_refs: [factorRef]}],
});
assert.deepStrictEqual(state.values, {factor_candidates: [frozenFactor]});
assert.strictEqual(state.settingsInitialized, false);
assert.strictEqual(window.FTTestState.restoreDraft(state, {
  schemaVersion: 1, kind: "backtest", values: {},
}), false);

const canonical = {
  analysis: {groups: [{id: "server", factor_candidate_refs: [factorRef]}]},
  savedFactors: [frozenFactor],
};
Object.assign(state, structuredClone(canonical));
assert.strictEqual(window.FTTestState.restoreDraft(state, {
  schemaVersion: 2, kind: "backtest", workspaceID: "workspace-tab-a",
  values: {
    analysis: {groups: [{id: "stale", factor_candidate_refs: [factorRef]}]},
    savedFactors: [], values: {factor_candidates: []},
  },
}), false);
assert.deepStrictEqual(state.analysis, canonical.analysis,
  "an inconsistent tab draft must not replace the canonical server workspace");
assert.deepStrictEqual(state.savedFactors, canonical.savedFactors);
console.log("ok");
