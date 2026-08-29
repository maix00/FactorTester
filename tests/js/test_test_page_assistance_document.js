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
    run_fields: {output_requests: [...state.outputRequests]},
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
  defaultRunValues: manifest => Object.fromEntries(
    (manifest.run_fields || []).filter(field => field.placement !== "outputs")
      .map(field => [field.key, structuredClone(field.default)]),
  ),
  registeredRunValues: state => Object.fromEntries(
    (state.manifest.run_fields || []).map(field => [field.key,
      field.placement === "outputs" ? state.outputRequests : state.runValues[field.key]]),
  ),
  applyRegisteredRunValues: (state, values) => {
    state.runValues = {task_name: values.task_name || ""};
    state.outputRequests = [...(values.output_requests || [])];
    state.outputRequestsExplicit = Array.isArray(values.output_requests);
  },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-page-assistance.js", "utf8"),
  {filename: "test-page-assistance.js"},
);

for (const kind of ["backtest", "ic"]) {
  const state = {
    kind,
    workspace: {configuration: {payload: {schema_version: 2, shared: {factors: []}}}},
    manifest: {
      defaults: {factor_mode: {tab_key: "factor-execution"}},
      modules: [
        {key: "factor-execution", label: "因子执行"},
        {key: "product-selection", label: "产品组"},
      ],
      field_contracts: {settings: {
        factor_mode: {module: "factor-execution", label: "因子模式"},
        product_path_selection: {module: "product-selection", label: "产品组"},
      }},
      run_fields: [
        {key: "task_name", label: "任务名称", placement: "run_identity", default: ""},
        {key: "output_requests", label: "结果与生成物", placement: "outputs",
          template_policy: "include", default: []},
      ],
    },
    values: {factor_mode: "native"},
    analysis: kind === "backtest"
      ? {groups: [{id: "strategy-1", factor_candidate_refs: ["factor:v2:test"]}]}
      : {configuration_groups: [{config_group_id: "ic-1", factor_ref: "factor:v2:test"}]},
    settingsMountedTabs: ["factor-execution"],
    outputRequests: ["equity_curve"],
    runValues: {task_name: `${kind} task`},
    selectedICConfigurationGroupIDs: kind === "ic" ? ["ic-1"] : [],
  };
  const document = FTTestPageAssistance.documentFor(state);
  assert.equal(document.document_kind, "research_configuration");
  assert.deepEqual(document.analyses, [kind]);
  assert.equal(document.configuration.schema_version, 2);
  assert.equal(document.configuration.analyses[kind].local_settings.factor_mode, "native");
  assert.equal(document.configuration.ui[kind].settings.factor_mode, "native");
  assert.deepEqual(document.configuration.run_fields.output_requests, ["equity_curve"]);
  assert.equal(document.configuration.ui[kind].output_requests, undefined);
  assert.equal(document.run_fields.task_name, `${kind} task`);
  assert.deepEqual(document.run_fields.output_requests, ["equity_curve"]);
  assert.equal(
    FTTestPageAssistance.schemaFor(state)["x-run-spec-shape"],
    "RunRequest(configuration + registered run_fields)",
  );
  const navigation = FTTestPageAssistance.navigationFor(state);
  assert.equal(navigation.nodes["tab:factor-execution"].mounted, true);
  assert.equal(navigation.nodes["tab:product-selection"].mounted, false);
  assert.deepEqual(
    navigation.nodes["tab:product-selection"].children,
    ["field:product_path_selection"],
    "unmounted tabs expose backend-registered fields without loading UI candidates",
  );
}

const importState = {
  kind: "backtest", workspace: null, manifest: {}, values: {}, analysis: {},
  settingsMountedTabs: [], outputRequests: [], selectedICConfigurationGroupIDs: [],
};
const configurationRuntime = global.FTTestConfiguration;
delete global.FTTestConfiguration;
let loadedGroup = "";
global.FTTestLazyCode = {
  loadGroup: group => {
    loadedGroup = group;
    global.FTTestConfiguration = configurationRuntime;
    return Promise.resolve();
  },
};
FTTestPageAssistance.register({}, importState, () => { restored += 1; });
assert.equal(
  global.FTTestConfiguration, undefined,
  "registering the page must not eagerly require the deferred configuration runtime",
);
registeredAdapter.prepare();
assert.equal(loadedGroup, "workbench-run-submit");
assert.equal(global.FTTestConfiguration, configurationRuntime);
registeredAdapter.importDocument({
  document_kind: "research_configuration",
  configuration: {schema_version: 2, shared: {}, analyses: {backtest: {groups: []}}, ui: {}},
  run_fields: {},
});
assert.equal(restored, 3, "the existing workspace restore helpers rebuild the page");
assert.deepEqual(importState.analysis, {groups: []});

console.log("PASS: test assistance edits the same configuration shape frozen by RunSpec");
