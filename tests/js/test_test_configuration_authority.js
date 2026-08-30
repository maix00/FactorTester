const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
vm.runInThisContext(
  fs.readFileSync(
    "server/manager/web/workbench/test-configuration-compiler.js", "utf8",
  ),
  {filename: "test-configuration-compiler.js"},
);

const manifest = {research_configuration_schema_version: 3, defaults: {
  start_date: {tab_key: "time", default: ""},
  end_date: {tab_key: "time", default: ""},
  start_time: {tab_key: "time", default: "00:00"},
  end_time: {tab_key: "time", default: "23:59"},
  editor_note: {tab_key: "notes", default: "", execution_policy: "authoring_only"},
}, tab_lists: {"local-settings": [
  {key: "time"}, {key: "notes"}, {key: "unused"},
]}, default_mounted_tabs: {"local-settings": ["unused"]}};
for (const kind of ["backtest", "ic", "future-test-kind"]) {
  const configuration = {
    schema_version: 3,
    analyses: {[kind]: {
      local_settings: {start_date: "wrong"},
      settings: {end_date: "wrong"},
    }},
    ui: {[kind]: {settings: {
      start_date: "2024-01-01", end_date: "2025-01-31",
      start_time: "09:00", end_time: "15:00", editor_note: "draft",
    }}},
  };
  const authoring = FTTestConfigurationCompiler.authoringConfiguration(
    configuration, kind,
  );
  assert.equal(authoring.analyses[kind].local_settings, undefined);
  assert.equal(authoring.analyses[kind].settings, undefined);
  const executable = FTTestConfigurationCompiler.executableConfiguration(
    authoring, kind, manifest,
  );
  assert.deepEqual(executable.analyses[kind].execution.settings, {
    start_date: "2024-01-01", end_date: "2025-01-31",
    start_time: "09:00", end_time: "15:00",
  });
  assert.equal(executable.analyses[kind].settings, undefined);
  assert.equal(executable.analyses[kind].local_settings, undefined);
  assert.deepEqual(FTTestConfigurationCompiler.authoringMountedTabs(
    manifest, configuration.ui[kind].settings, [],
  ), ["time", "notes"]);
}

console.log("PASS: every test kind derives executable settings from registered UI fields");
