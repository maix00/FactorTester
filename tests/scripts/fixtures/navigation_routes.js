const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
global.FTIcons = {module: () => null};
vm.runInThisContext(
  fs.readFileSync("scripts/worktree_manager_web/app/navigation.js", "utf8"),
  {filename: "navigation.js"},
);

const match = window.FTNavigation.matchRoute;
assert.deepStrictEqual(match("/", ""), {kind: "home"});
assert.deepStrictEqual(match("/research", "?section=graph"), {kind: "research"});
assert.deepStrictEqual(match("/research/local%3Aid", ""), {
  kind: "report", id: "local%3Aid",
});
assert.deepStrictEqual(match("/jobs/8141/job%2Fid", ""), {
  kind: "job", port: 8141, id: "job/id",
});
assert.deepStrictEqual(match("/reference", "?kind=evidence&target=evidence%3A1&label=证据"), {
  kind: "reference", referenceKind: "evidence", target: "evidence:1", label: "证据",
});
assert.deepStrictEqual(match("/products/continuous-contract/CA%5Bmain%5D", ""), {
  kind: "product-reference", referenceKind: "continuous-contract", id: "CA[main]",
});
assert.deepStrictEqual(match("/not-registered", ""), {kind: "unknown"});
console.log("ok");
