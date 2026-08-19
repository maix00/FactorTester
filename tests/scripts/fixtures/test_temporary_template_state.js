const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.FTTestLazyCode = {
  fallbackGroupReferences: () => ["inline-product-group:session"],
  groupID: value => value?.group_ref || value?.id || "",
};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "test-state.js",
});

const state = {
  kind: "ic",
  workspace: {configuration: {payload: {
    shared: {
      factors: [{factor_ref: "factor:inline", factor_alias: "InlineFactor"}],
      factor_families: [],
      temporary_objects: {
        factors: [{
          factor_ref: "factor:inline", factor_alias: "InlineFactor", temporary: true,
        }],
        product_groups: [{
          id: "inline-product-group:session", temporary: true, paths: ["CNFutures/**"],
        }],
        categories: [{id: "inline-category:session", temporary: true}],
        factor_sources: [{
          factor_id: "InlineFactor", path: "inline/InlineFactor.py",
          source_code: "class InlineFactor: pass\n",
        }],
      },
    },
    analyses: {ic: {}},
    ui: {ic: {product_group_refs: ["inline-product-group:session"]}},
  }}},
  values: {factor_candidates: [], category_candidates: []},
};

window.FTTestState.applyWorkspaceConfiguration(state);
window.FTTestState.seedSavedCatalogs(state);
assert.equal(state.values.factor_candidates[0].factor_alias, "InlineFactor");
assert.equal(state.values.category_candidates[0].id, "inline-category:session");
assert.equal(state.groups[0].id, "inline-product-group:session");
assert.equal(state.transientFactorSources[0].source_code, "class InlineFactor: pass\n");
console.log("ok");
