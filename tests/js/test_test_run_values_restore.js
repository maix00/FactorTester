const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
global.FTTestLazyCode = {fallbackGroupReferences: () => [], groupID: () => ""};
global.FTTestProducts = {restoreReferences: () => []};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-state.js", "utf8"),
  {filename: "test-state.js"},
);

const state = {
  kind: "backtest",
  manifest: {run_fields: [
    {key: "task_name", placement: "run_identity", default: ""},
    {key: "retention_mode", placement: "run_identity", default: "summary"},
  ]},
  workspace: {configuration: {payload: {
    analyses: {backtest: {groups: []}},
    ui: {backtest: {run_values: {task_name: "Self 写入的任务名称"}}},
  }}},
};
FTTestState.applyWorkspaceConfiguration(state);
assert.deepEqual(state.runValues, {
  task_name: "Self 写入的任务名称", retention_mode: "summary",
});
console.log("PASS: assisted run fields restore into the visible test controls");
