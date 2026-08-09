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
const pinned = window.FTNavigation.isPinnedPath;
const modules = [
  {id: "products", title: "产品", path: "/products"},
];
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
  componentID: "", detailFields: [],
});
const details = encodeURIComponent(JSON.stringify([
  {name: "port", value: "8141"}, {name: "scope", value: "报告"},
]));
assert.deepStrictEqual(match("/reference", `?kind=job&target=job%3A1&label=任务&component_id=entry-1&details=${details}`), {
  kind: "reference", referenceKind: "job", target: "job:1", label: "任务",
  componentID: "entry-1",
  detailFields: [{name: "port", value: "8141"}, {name: "scope", value: "报告"}],
});
assert.deepStrictEqual(match("/products/continuous-contract/CA%5Bmain%5D", ""), {
  kind: "product-reference", referenceKind: "continuous-contract", id: "CA[main]",
});
assert.deepStrictEqual(match("/factors/sets", ""), {kind: "factor-sets"});
assert.strictEqual(pinned("/products?source=local"), true);
assert.strictEqual(pinned("/products/sources?source=local"), true);
assert.strictEqual(pinned("/products/groups"), true);
assert.strictEqual(pinned("/products/product/A.DCE"), false);
assert.strictEqual(pinned("/factors/sets"), true);
assert.strictEqual(
  window.FTNavigation.moduleForPath("/products/groups?source=local", modules).id,
  "products",
);
assert.deepStrictEqual(match("/not-registered", ""), {kind: "unknown"});
console.log("ok");
