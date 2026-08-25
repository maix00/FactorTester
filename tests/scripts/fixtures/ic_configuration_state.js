const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = global.structuredClone
  || (value => JSON.parse(JSON.stringify(value)));

function load(path) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
}

load("server/manager/web/workbench/test-lazy-code.js");
global.FTTestLazyCode = window.FTTestLazyCode;
load("server/manager/web/workbench/configuration-groups/ic/model.js");
global.FTICConfigurationGroupModel = window.FTICConfigurationGroupModel;
load("server/manager/web/workbench/test-state.js");

const factorRef = `factor:v2:${"a".repeat(43)}`;
const frozenFactor = {
  schema_version: 2, ref: factorRef, alias: "ROC",
  owner_ref: "owner:alice", identity: {family_ref: "family:roc"},
};
const group = {
  config_group_id: "icg-day",
  batch_id: "icb-day",
  name: "日盘 ROC",
  factor_ref: factorRef,
  product_scope_ref: "product-group:day",
  entry_delay_bars: 0,
  horizon: {sampling: "scale_aware"},
  methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
};
const state = {
  kind: "ic",
  manifest: {run_fields: []},
  workspace: {
    workspace_id: "workspace-ic",
    configuration: {payload: {
      shared: {factors: [frozenFactor]},
      analyses: {ic: {
        schema_version: 2,
        configuration_groups: [group],
        product_selections: {
          "product-group:day": {product_path_selection_id: "product-group:day"},
        },
        local_settings: {start_date: "2025-01-02"},
      }},
      // Selection metadata is optional for a Slice-1 payload: the only valid
      // group must be selected when restored.
      ui: {ic: {}},
    }},
  },
  values: {},
};

window.FTTestState.applyWorkspaceConfiguration(state);
assert.deepEqual(state.analysis.configuration_groups, [
  {...group, analysis_attachments: [], editor_mounted_tabs: [
    "__configuration__", "factor", "product_path_selection",
  ]},
]);
assert.deepEqual(state.selectedICConfigurationGroupIDs, ["icg-day"]);
assert.equal(state.factorRef, factorRef);
assert.deepEqual(state.groupRefs, ["product-group:day"]);
assert.equal(state.groupRef, "product-group:day");

window.FTTestState.seedSavedCatalogs(state);
assert.equal(state.groups.length, 1);
assert.equal(window.FTTestLazyCode.groupID(state.groups[0]), "product-group:day");
assert.deepEqual(state.groups[0], {product_path_selection_id: "product-group:day"});

state.icConfigurationGroupsOpen = true;
state.icConfigurationGroupEditor = {mode: "edit", groupID: "icg-day"};
const snapshot = window.FTTestState.draftSnapshot(state);
state.selectedICConfigurationGroupIDs = [];
state.icConfigurationGroupsOpen = false;
state.icConfigurationGroupEditor = null;
assert.equal(window.FTTestState.restoreDraft(state, snapshot), true);
assert.deepEqual(state.selectedICConfigurationGroupIDs, ["icg-day"]);
assert.equal(state.icConfigurationGroupsOpen, true);
assert.deepEqual(state.icConfigurationGroupEditor, {mode: "edit", groupID: "icg-day"});

window.FTTestState.clearDraft(state);
assert.deepEqual(state.selectedICConfigurationGroupIDs, []);
assert.equal(state.icConfigurationGroupsOpen, false);
assert.equal(state.icConfigurationGroupEditor, null);

const legacy = {
  kind: "ic",
  manifest: {run_fields: []},
  workspace: {
    workspace_id: "workspace-legacy",
    configuration: {payload: {
      shared: {factors: [frozenFactor]},
      analyses: {ic: {
        factors: [{factor_ref: factorRef}],
        product_path_selection_id: "product-group:legacy",
        local_settings: {
          ic_lags: [2],
          forward_return_horizons: {sampling: "scale_aware"},
          ic_correlation: "rank",
          return_price_basis: "next_close_to_close_adjusted",
        },
      }},
      ui: {ic: {}},
    }},
  },
  values: {},
};
window.FTTestState.applyWorkspaceConfiguration(legacy);
assert.equal(legacy.analysis.legacy_flat_migrated, true);
assert.equal(legacy.analysis.configuration_groups.length, 1);
assert.deepEqual(legacy.selectedICConfigurationGroupIDs, [
  legacy.analysis.configuration_groups[0].config_group_id,
]);
assert.deepEqual(legacy.groupRefs, ["product-group:legacy"]);

console.log("ok");
