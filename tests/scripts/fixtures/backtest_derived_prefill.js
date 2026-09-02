const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const values = new Map();
global.sessionStorage = {
  getItem: key => values.get(key) || null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: key => values.delete(key),
};
global.window = globalThis;
global.window.location = {search: ""};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/core/test-type-registry.js", "utf8",
), {filename: "test-type-registry.js"});
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "tests.js",
});

values.set("ft-backtest-derived-prefill", JSON.stringify({
  workspaceID: "workspace-restored",
  parentID: "group-1",
  products: ["SI.GFE", "EC.INE"],
  name: "A1 精选",
}));
const state = {
  kind: "backtest",
  workspace: {workspace_id: "workspace-restored"},
  analysis: {groups: [{id: "group-1"}]},
};
FTTests.applyBacktestDerivedPrefill(state);
assert.deepEqual(state.backtestGroupEditor, {
  mode: "derived", parentID: "group-1",
  productMask: ["SI.GFE", "EC.INE"], name: "A1 精选",
});
assert.equal(state.backtestGroupsOpen, true);
assert.equal(values.has("ft-backtest-derived-prefill"), false);

values.set("ft-backtest-derived-prefill", JSON.stringify({
  workspaceID: "another-workspace", parentID: "group-1", products: ["SI.GFE"],
}));
state.backtestGroupEditor = null;
FTTests.applyBacktestDerivedPrefill(state);
assert.equal(state.backtestGroupEditor, null);
assert.equal(values.has("ft-backtest-derived-prefill"), true);
console.log("ok");
