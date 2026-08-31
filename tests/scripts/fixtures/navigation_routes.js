const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

global.window = {};
global.FTIcons = {module: () => null};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/app/navigation.js", "utf8"),
  {filename: "navigation.js"},
);

const match = window.FTNavigation.matchRoute;
const pinned = window.FTNavigation.isPinnedPath;
const modules = [
  {id: "products", title: "产品库", path: "/products"},
];
assert.deepStrictEqual(match("/", ""), {kind: "home"});
assert.deepStrictEqual(match("/research", "?section=graph"), {kind: "research"});
assert.deepStrictEqual(match("/jobs", ""), {kind: "jobs", section: "types"});
assert.deepStrictEqual(match("/jobs", "?scope=mine"), {kind: "jobs", section: "tasks"});
assert.deepStrictEqual(match("/jobs", "?section=tasks"), {kind: "jobs", section: "tasks"});
assert.deepStrictEqual(match("/jobs", "?section=unknown"), {kind: "jobs", section: "types"});
assert.deepStrictEqual(match("/mihomo", ""), {kind: "mihomo"});
assert.deepStrictEqual(match("/docs", ""), {kind: "docs", slug: ""});
assert.deepStrictEqual(match("/docs/system-overview", ""), {
  kind: "docs", slug: "system-overview",
});
assert.deepStrictEqual(match("/research/local%3Aid", ""), {
  kind: "report", id: "local%3Aid",
});
assert.deepStrictEqual(match("/jobs/8141/job%2Fid", ""), {
  kind: "job", port: 8141, id: "job/id",
});
assert.deepStrictEqual(match("/jobs/8141/job-one/configuration", ""), {
  kind: "job-configuration", port: 8141, id: "job-one",
});
assert.deepStrictEqual(match("/jobs/job-one/configuration", ""), {
  kind: "job-configuration", port: 0, id: "job-one",
});
assert.deepStrictEqual(match("/jobs/8141/job-one/inputs/factor_source__Demo", ""), {
  kind: "job-input", port: 8141, id: "job-one", inputName: "factor_source__Demo",
});
assert.deepStrictEqual(match("/jobs/job-one/inputs/factor_source__Demo", ""), {
  kind: "job-input", port: 0, id: "job-one", inputName: "factor_source__Demo",
});
assert.deepStrictEqual(match("/ic-test", ""), {kind: "ic-test"});
assert.deepStrictEqual(match(
  "/ic-test", "?workspace_id=ws-1&job_id=job-1&run_id=run-1&port=8141&server_id=public-1",
), {
  kind: "ic-test", workspaceID: "ws-1", restoredJob: {
    jobID: "job-1", runID: "run-1", runSpecHash: "", phase: "succeeded",
    port: 8141, serverID: "public-1", groupID: "",
  },
});
assert.deepStrictEqual(match("/backtest", ""), {kind: "backtest"});
assert.deepStrictEqual(match(
  "/factor-series",
  "?factor_ref=factor%3Av1%3Aone&group_ref=product-group%3Anight",
), {
  kind: "factor-series", factorRef: "factor:v1:one",
  groupRef: "product-group:night",
});
assert.strictEqual(pinned("/factor-series?factor_ref=factor%3Av1%3Aone"), false);
assert.strictEqual(pinned("/reference"), true);
assert.strictEqual(
  pinned("/reference?kind=run-spec&target=runspec%3Asha256%3Aabc"), false,
);
assert.deepStrictEqual(match("/reference", "?kind=run-spec&target=run-spec%3Asha256%3Aabc"), {
  kind: "reference", referenceKind: "run-spec", target: "run-spec:sha256:abc",
  label: "", componentID: "", detailFields: [],
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
assert.deepStrictEqual(match("/factors/sets", ""), {kind: "factor-sets", scope: "mine"});
assert.deepStrictEqual(match("/factors/sets", "?scope=subordinates"), {
  kind: "factor-sets", scope: "subordinates",
});
assert.deepStrictEqual(match("/factors", "?scope=subordinates"), {
  kind: "factors", scope: "subordinates",
});
assert.deepStrictEqual(match("/factors/families", ""), {
  kind: "factor-families", scope: "public",
});
assert.deepStrictEqual(match("/factors/families", "?scope=subordinates"), {
  kind: "factor-families", scope: "subordinates",
});
assert.deepStrictEqual(match("/factors/families", "?scope=unknown"), {
  kind: "factor-families", scope: "public",
});
assert.deepStrictEqual(match("/factors/family/new", "?mode=create&visibility=public"), {
  kind: "factor-family", id: "", mode: "create", publicMode: true,
});
assert.deepStrictEqual(match(
  "/factors/factor/new", "?mode=create&family_ref=family%3Aone",
), {
  kind: "factor", id: "", mode: "create", familyRef: "family:one",
});
assert.deepStrictEqual(match("/factors/family/family%3Aone", "?mode=edit"), {
  kind: "factor-family", id: "family:one", mode: "edit", publicMode: false,
});
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
