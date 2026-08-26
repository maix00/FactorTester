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
const inlineFactor = {
  schema_version: 2,
  ref: `factor:v2:${"a".repeat(43)}`,
  alias: "InlineFactor",
  owner_ref: "profile:maxa",
  identity: {
    family_ref: `factor-family:v2:${"b".repeat(43)}`,
    family_alias: "InlineFamily",
    family_formula_fingerprint: "c".repeat(64),
    self_formula_fingerprint: "d".repeat(64),
    params: {},
  },
};

const state = {
  kind: "ic",
  workspace: {configuration: {payload: {
    shared: {
      factors: [inlineFactor],
      factor_families: [],
      temporary_objects: {
        factors: [{
          ...inlineFactor, temporary: true,
        }],
        factor_sets: [{
          target_ref: "factor-set:v1:temporary", temporary: true,
          manifest: {identity: {members: []}},
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
    analyses: {ic: {product_selections: {
      "inline-product-group:session": {
        product_path_selection_id: "inline-product-group:session",
        selected_paths: ["CNFutures/**"],
      },
    }}},
    ui: {ic: {product_group_refs: ["inline-product-group:session"]}},
  }}},
  values: {factor_candidates: [], category_candidates: []},
};

window.FTTestState.applyWorkspaceConfiguration(state);
window.FTTestState.seedSavedCatalogs(state);
assert.equal(state.values.factor_candidates[0].alias, "InlineFactor");
assert.equal(state.values.category_candidates[0].id, "inline-category:session");
assert.equal(state.groups[0].id, "inline-product-group:session");
assert.equal(
  state.groups[0].temporary,
  true,
  "a compact frozen selection must not erase the richer temporary object",
);
assert.equal(state.transientFactorSources[0].source_code, "class InlineFactor: pass\n");
assert.equal(
  state.savedTemporaryObjects.factor_sets[0].target_ref,
  "factor-set:v1:temporary",
);
console.log("ok");
