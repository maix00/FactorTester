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
  start_date: {tab_key: "time", value: ""},
  end_date: {tab_key: "time", value: ""},
  start_time: {tab_key: "time", value: "00:00"},
  end_time: {tab_key: "time", value: "23:59"},
  editor_note: {tab_key: "notes", value: "", execution_policy: "authoring_only"},
  object_default: {
    tab_key: "notes", value: {mode: "auto", count: 5},
    execution_policy: "authoring_only",
  },
}, tab_lists: {"local-settings": [
  {key: "time"}, {key: "notes"}, {key: "unused"},
]}, default_mounted_tabs: {"local-settings": ["unused"]}, strategy_editor: {
  inner_default_tabs: [
    {key: "__configuration__"}, {key: "factor"}, {key: "product_path_selection"},
  ],
  inner_manual_tabs: [
    {key: "time", item_field: "start_date", item_default: ""},
    {key: "delay", item_field: "entry_delay_bars", item_default: 0},
  ],
}};
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
      object_default: {count: 5, mode: "auto"},
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
  ), ["time", "notes", "unused"]);
  assert.deepEqual(FTTestConfigurationCompiler.authoringMountedTabs(
    manifest, {
      start_date: "", end_date: "", start_time: "00:00", end_time: "23:59",
      editor_note: "",
      object_default: {count: 5, mode: "auto"},
    }, [],
  ), ["unused"]);
  assert.deepEqual(FTTestConfigurationCompiler.authoringMountedTabs(
    manifest, {start_time: "00:00", end_time: "23:59"}, ["notes"],
  ), ["notes", "unused"]);
  assert.deepEqual(FTTestConfigurationCompiler.authoringItemMountedTabs(
    manifest, {start_date: "2024-01-01", entry_delay_bars: 0}, [],
  ), ["__configuration__", "factor", "product_path_selection", "time"]);
  assert.deepEqual(FTTestConfigurationCompiler.authoringItemMountedTabs(
    manifest, {start_date: "", entry_delay_bars: 3}, [],
  ), ["__configuration__", "factor", "product_path_selection", "delay"]);
  assert.deepEqual(FTTestConfigurationCompiler.authoringItemMountedTabs(
    manifest, {start_date: "", entry_delay_bars: 0}, ["delay"],
  ), ["__configuration__", "factor", "product_path_selection", "delay"]);
}

console.log("PASS: every test kind derives executable settings from registered UI fields");
