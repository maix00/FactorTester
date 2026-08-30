const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = global;
global.structuredClone = value => JSON.parse(JSON.stringify(value));

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-state.js", "utf8",
));

const state = {
  kind: "backtest",
  manifest: {settings_tabs: []},
  workspace: {
    configuration: {
      payload: {
        ui: {
          backtest: {
            mounted_tabs: ["task_submission", "time"],
            explicit_mounted_tabs: ["time"],
            settings: {start_date: "2024-01-01"},
          },
        },
      },
    },
  },
};

assert.deepStrictEqual(
  FTTestState.savedMountedTabs(state),
  ["task_submission", "time"],
  "saved mounted tabs must remain readable before the compiler is loaded",
);

let compilerCall;
global.FTTestConfigurationCompiler = {
  authoringMountedTabs(manifest, settings, explicit) {
    compilerCall = {manifest, settings, explicit};
    return ["canonical"];
  },
};

assert.deepStrictEqual(FTTestState.savedMountedTabs(state), ["canonical"]);
assert.deepStrictEqual(compilerCall.settings, {start_date: "2024-01-01"});
assert.deepStrictEqual(compilerCall.explicit, ["time"]);

console.log("test-state compiler load-order checks passed");
