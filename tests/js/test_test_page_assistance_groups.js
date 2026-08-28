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
global.FTTestState = {
  applyWorkspaceConfiguration: state => {
    state.analysis = structuredClone(
      state.workspace.configuration.payload.analyses.backtest,
    );
  },
  seedSavedCatalogs: () => {},
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
  kind: "backtest", manifest: {}, workspace: null,
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
assert.throws(() => registration.validate({
  document_kind: "research_configuration",
  configuration: {schema_version: 2, analyses: {backtest: {groups: []}}},
}), /至少需要一个策略/);
registration.importDocument({configuration: state.payload});
assert.deepEqual(state.analysis.groups, [group]);
assert.equal(initialized, 1, "imported strategy groups enter the normal UI model");

const nextController = FTTestPageAssistance.register(
  {...context, pageState: {}}, state, () => {},
);
assert.equal(registrationCount, 2,
  "a newly restored PageState receives a fresh assistance lifecycle");
assert.notEqual(nextController, firstController);
console.log("PASS: assisted backtest documents preserve required strategy groups");
