const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/test-products.js", "utf8"),
  {filename: "test-products.js"},
);

(async () => {
  const ref = "product-group:pg_saved";
  const requests = [];
  const groups = await FTTestProducts.hydrateReferencedGroups({
    api: async path => {
      requests.push(path);
      return {group: {group_ref: ref, name: "已保存产品组", paths: ["DCE.m"]}};
    },
  }, {groupRefs: [ref]}, []);
  assert.deepEqual(requests, [
    `/api/catalog/product-groups/${encodeURIComponent(ref)}`,
  ]);
  assert.equal(groups[0].group_ref, ref);
  assert.equal(groups[0].name, "已保存产品组");

  const listed = [{group_ref: ref, name: "目录产品组"}];
  const unchanged = await FTTestProducts.hydrateReferencedGroups({
    api: async () => { throw new Error("must not fetch"); },
  }, {groupRefs: [ref]}, listed);
  assert.equal(unchanged, listed);

  const state = {
    kind: "backtest",
    groupRef: ref,
    groupRefs: [ref],
    groups: [{
      group_ref: ref, title_zh: ref, paths: [], selected_paths: [],
      _savedPlaceholder: true,
    }],
    values: {},
  };
  assert.equal(FTTestProducts.needsReferenceHydration(state), true);
  const changed = await FTTestProducts.hydrateStateReferences({
    api: async path => {
      assert.equal(path, `/api/catalog/product-groups/${encodeURIComponent(ref)}`);
      return {group: {group_ref: ref, name: "中国期货日盘", paths: ["DCE.m"]}};
    },
  }, state);
  assert.equal(changed, true);
  assert.equal(FTTestProducts.needsReferenceHydration(state), false);
  assert.equal(state.groups[0].name, "中国期货日盘");
  assert.equal(state.values.product_path_selections[0].label, "中国期货日盘");
  console.log("PASS: persisted product-group refs hydrate independently of list catalogs");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
