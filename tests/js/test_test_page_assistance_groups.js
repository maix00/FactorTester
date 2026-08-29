const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
let registration = null;
let registrationCount = 0;
global.FTPageAssistance = {
  register: (_context, assistance) => {
    registrationCount += 1;
    registration = assistance;
    return {id: registrationCount};
  },
};
global.FTTestLazyCode = {loadGroup: async () => {}};
global.FTTestConfiguration = {configurationPayload: state => state.payload};
global.FTTestConfigurationCompiler = {
  authoringSettings: (_manifest, values) => ({...(values || {})}),
  authoringMountedTabs: (_manifest, _settings, saved) => [...(saved || [])],
  executionSettings: (_manifest, values) => ({...(values || {})}),
  derivedSettingsKeys: () => ["execution", "local_settings", "settings"],
  authoringConfiguration: configuration => structuredClone(configuration),
  executableConfiguration: configuration => structuredClone(configuration),
};
global.FTTestState = {
  applyWorkspaceConfiguration: state => {
    state.analysis = structuredClone(
      state.workspace.configuration.payload.analyses.backtest,
    );
  },
  seedSavedCatalogs: () => {},
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
let initialized = 0;
global.FTBacktestGroupModel = {initialize: () => { initialized += 1; }};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-page-assistance.js", "utf8"),
  {filename: "test-page-assistance.js"},
);

const group = {
  id: "strategy-1", factor_candidate_refs: ["factor:1"],
  product_path_selection: {group_ref: "product-group:1"},
  splitCount: 5, groupIndex: 1,
};
const state = {
  kind: "backtest", manifest: {
    configuration_item_contract: {
      schema_version: 1, item_kind: "strategy", collection_key: "groups",
      min_items: 1,
      schema: {
        type: "object",
        required: [
          "id", "factor_candidate_refs", "product_path_selection",
          "splitCount", "groupIndex",
        ],
        properties: {},
      },
    },
    run_fields: [
    {key: "task_name", label: "任务名称", placement: "run_identity", default: "",
      value_descriptor: {editor: "text"}},
    {key: "output_requests", label: "结果与生成物", placement: "outputs", default: [],
      value_descriptor: {editor: "output_picker"}},
  ]}, workspace: null, runValues: {task_name: "原名称"}, outputRequests: ["equity_curve"],
  payload: {schema_version: 2, analyses: {backtest: {groups: [group]}}},
};
const pageState = {};
const context = {t: value => value, pageState};
const firstController = FTTestPageAssistance.register(context, state, () => {});
const rerenderController = FTTestPageAssistance.register(context, state, () => {});
assert.equal(registrationCount, 1,
  "rerendering one test tab keeps its existing drawer and ChatKit stream");
assert.equal(rerenderController, firstController);
const schema = registration.schema();
assert.equal(
  schema.properties.configuration.properties.analyses
    .properties.backtest.properties.groups.minItems,
  1,
  "the Agent receives the strategy-group requirement in the document schema",
);
assert.equal(
  schema.properties.run_fields.properties.task_name.description,
  "任务名称",
  "the Agent schema exposes registered per-run fields outside configuration",
);
assert.throws(() => registration.validate({
  document_kind: "research_configuration",
  configuration: {schema_version: 2, analyses: {backtest: {groups: []}}},
}), /至少需要一个策略/);
assert.throws(() => registration.validate({
  document_kind: "research_configuration",
  configuration: {
    schema_version: 2,
    analyses: {backtest: {groups: [group], task_name: "wrong"}},
  },
  run_fields: {},
}), /文档顶层 run_fields/);
registration.importDocument({
  configuration: state.payload,
  run_fields: {task_name: "Self 写入名称", output_requests: ["period_returns"]},
});
assert.deepEqual(state.analysis.groups, [group]);
assert.equal(state.runValues.task_name, "Self 写入名称");
assert.deepEqual(state.outputRequests, ["period_returns"]);
assert.equal(initialized, 1, "imported strategy groups enter the normal UI model");

const nextController = FTTestPageAssistance.register(
  {...context, pageState: {}}, state, () => {},
);
assert.equal(registrationCount, 2,
  "a newly restored PageState receives a fresh assistance lifecycle");
assert.notEqual(nextController, firstController);
console.log("PASS: assisted backtest documents preserve required strategy groups");
