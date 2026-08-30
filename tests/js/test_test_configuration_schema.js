const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
global.FTTestFactors = {
  selectedFactor: () => null,
  selectedFamily: () => null,
};
global.FTTestProducts = {
  synchronize: () => {},
  groupID: () => "",
  projection: value => value,
};
global.FTTestState = {registeredRunValues: () => ({})};
global.FTTestConfigurationCompiler = {
  executionSettings: () => ({}),
  authoringSettings: () => ({}),
};

vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-configuration.js", "utf8"),
  {filename: "test-configuration.js"},
);

function state(schemaVersion) {
  return {
    kind: "backtest",
    manifest: {research_configuration_schema_version: schemaVersion},
    workspace: {configuration: {payload: {
      schema_version: 999, shared: {}, analyses: {}, ui: {},
    }}},
    analysis: {groups: []},
    values: {},
    settingsMountedTabs: [],
    groups: [],
  };
}

const payload = FTTestConfiguration.configurationPayload(
  state(3), null, {allowIncomplete: true},
);
assert.equal(
  payload.schema_version,
  3,
  "authoring payload uses the backend manifest instead of a frontend constant",
);
assert.throws(
  () => FTTestConfiguration.configurationPayload(
    state(undefined), null, {allowIncomplete: true},
  ),
  /缺少 ResearchConfiguration schema 版本/,
);

console.log("PASS: test configuration schema version has one backend authority");
