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

const manifest = {run_fields: [
  {key: "task_name", placement: "run_identity", template_policy: "exclude", default: ""},
  {key: "service_port", placement: "global_settings", template_policy: "exclude", default: ""},
  {key: "retention_mode", placement: "run_options", template_policy: "exclude",
    default: "summary"},
  {key: "output_requests", placement: "outputs", template_policy: "include", default: []},
]};
const state = {
  kind: "backtest", manifest,
  workspace: {configuration: {payload: {
    analyses: {backtest: {groups: []}},
    run_fields: {output_requests: ["equity_curve"]},
    ui: {backtest: {}},
  }}},
};
FTTestState.applyWorkspaceConfiguration(state);
assert.deepEqual(state.runValues, {
  task_name: "", service_port: "", retention_mode: "summary",
});
assert.deepEqual(state.outputRequests, ["equity_curve"]);
assert.equal(state.outputRequestsExplicit, true);
console.log("PASS: reusable and per-run registered fields restore without UI metadata");
