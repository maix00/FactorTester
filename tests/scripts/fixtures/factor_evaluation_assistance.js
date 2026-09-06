const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = value => JSON.parse(JSON.stringify(value));
global.FTTestConfigurationCompiler = {
  authoringConfiguration: value => value,
  authoringMountedTabs: (_manifest, _settings, mounted) => mounted || [],
  authoringItemMountedTabs: () => [],
  derivedSettingsKeys: () => [],
  executableConfiguration: value => value,
};
global.FTTestConfiguration = {
  configurationPayload: state => state.configuration,
};
global.FTTestState = {registeredRunValues: state => state.runValues};
window.FTTestConfigurationCompiler = global.FTTestConfigurationCompiler;
window.FTTestConfiguration = global.FTTestConfiguration;
window.FTTestState = global.FTTestState;

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-page-assistance.js", "utf8",
), {filename: "test-page-assistance.js"});

const state = {
  kind: "factor_evaluation",
  configuration: {
    schema_version: 2,
    analyses: {factor_evaluation: {
      factor_ref: "factor:v2:one",
      factor_alias: "MmOne|N:20d",
      product_path_selection_id: "product-group:all",
      product_path_selection: {selected_paths: ["CNFutures/**"]},
      execution: {settings: {frequency: "DAY1"}},
    }},
    ui: {factor_evaluation: {mounted_tabs: ["factor", "time"], settings: {}}},
  },
  runValues: {retention_mode: "full", output_requests: ["factor_series"]},
  manifest: {
    research_configuration_schema_version: 2,
    configuration_item_contract: {schema: {type: "object"}},
    run_fields: [], field_contracts: {settings: {}}, chip_fields: [],
    modules: [
      {key: "factor", label: "因子"},
      {key: "time", label: "时间范围"},
    ],
  },
};

const schema = window.FTTestPageAssistance.schemaFor(state);
const analysis = schema.properties.configuration.properties.analyses
  .properties.factor_evaluation;
assert.deepEqual(analysis.required, ["factor_ref", "product_path_selection"]);
assert.equal(analysis.properties.factor_ref.type, "string");
assert.equal(analysis.properties.factor_ref.minLength, undefined);
for (const kind of ["ic", "backtest"]) {
  const draftSchema = window.FTTestPageAssistance.schemaFor({...state, kind});
  const fields = draftSchema.properties.configuration.properties.analyses.properties[kind].properties;
  assert.equal(fields[kind === "ic" ? "configuration_groups" : "groups"].minItems, 0);
}

const navigation = window.FTTestPageAssistance.navigationFor(state);
assert.equal(navigation.nodes.page.label, "查看因子序列配置");
assert.deepEqual(navigation.nodes.page.children, ["tab:factor", "tab:time"]);
assert.equal(navigation.nodes.configurations, undefined);
console.log("ok");
