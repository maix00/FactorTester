const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
global.FTTestConfigurationCompiler = {
  authoringSettings: (_manifest, values) => ({...values}),
  executionSettings: (_manifest, values) => ({factor_mode: values.factor_mode}),
};
global.FTTestConfiguration = {
  configurationPayload: state => ({
    schema_version: 2,
    shared: state.workspace.configuration.payload.shared,
    analyses: {
      [state.kind]: {
        ...state.analysis,
        local_settings: {factor_mode: state.values.factor_mode},
      },
    },
    ui: {
      [state.kind]: {
        settings: {...state.values},
        mounted_tabs: [...state.settingsMountedTabs],
        output_requests: [...state.outputRequests],
      },
    },
  }),
};
let registeredAdapter = null;
global.FTPageAssistance = {
  register: (_context, adapter) => { registeredAdapter = adapter; return adapter; },
};
let restored = 0;
global.FTTestState = {
  applyWorkspaceConfiguration: state => {
    state.analysis = state.workspace.configuration.payload.analyses[state.kind];
    restored += 1;
  },
  seedSavedCatalogs: () => { restored += 1; },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-page-assistance.js", "utf8"),
  {filename: "test-page-assistance.js"},
);

for (const kind of ["backtest", "ic"]) {
  const state = {
    kind,
    workspace: {configuration: {payload: {schema_version: 2, shared: {factors: []}}}},
    manifest: {defaults: {factor_mode: {tab_key: "factor-execution"}}},
    values: {factor_mode: "native"},
    analysis: kind === "backtest"
      ? {groups: [{id: "strategy-1", factor_candidate_refs: ["factor:v2:test"]}]}
      : {configuration_groups: [{config_group_id: "ic-1", factor_ref: "factor:v2:test"}]},
    settingsMountedTabs: ["factor-execution"],
    outputRequests: ["equity_curve"],
    selectedICConfigurationGroupIDs: kind === "ic" ? ["ic-1"] : [],
  };
  const document = FTTestPageAssistance.documentFor(state);
  assert.equal(document.document_kind, "research_configuration");
  assert.deepEqual(document.analyses, [kind]);
  assert.equal(document.configuration.schema_version, 2);
  assert.equal(document.configuration.analyses[kind].local_settings.factor_mode, "native");
  assert.equal(document.configuration.ui[kind].settings.factor_mode, "native");
  assert.equal(
    FTTestPageAssistance.schemaFor(state)["x-run-spec-shape"],
    "RunSpec.configuration",
  );
}

const importState = {
  kind: "backtest", workspace: null, manifest: {}, values: {}, analysis: {},
  settingsMountedTabs: [], outputRequests: [], selectedICConfigurationGroupIDs: [],
};
FTTestPageAssistance.register({}, importState, () => { restored += 1; });
registeredAdapter.importDocument({
  document_kind: "research_configuration",
  configuration: {schema_version: 2, shared: {}, analyses: {backtest: {groups: []}}, ui: {}},
});
assert.equal(restored, 3, "the existing workspace restore helpers rebuild the page");
assert.deepEqual(importState.analysis, {groups: []});

console.log("PASS: test assistance edits the same configuration shape frozen by RunSpec");
