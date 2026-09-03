const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

// The row viewer helpers must classify every picker object row by kind and
// route library rows to the ref-based view overlay while test-local rows
// (created inline in a test editor, never persisted) stay viewable through
// their carried frozen value.
const body = {children: []};
global.window = {innerWidth: 1024, innerHeight: 768};
global.document = {body, createElement: () => ({})};
for (const source of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(source, "utf8"), {filename: source});
}
const shared = window.FTFactorDetailShared;
assert.ok(shared, "factor-detail-shared must load");

// Library factor → open by ref, no frozen payload needed.
const library = shared.factorRowView({
  ref: "factor:v2:lib1", alias: "LibFactor", source_kind: "library",
});
assert.deepEqual(library, {kind: "factor", ref: "factor:v2:lib1", title: "查看因子"});

// Test-inline factor (created on the test page) → viewable from frozen value.
const inlineFactor = shared.factorRowView({
  ref: "factor:v2:local1", alias: "InlineFactor",
  source_kind: "transient", source_origin: "test_inline",
  factor_family_alias: "FamilyA", math_expr: "x + 1",
});
assert.equal(inlineFactor.kind, "factor");
assert.equal(inlineFactor.temporary, true, "inline factor view is temporary");
assert.equal(inlineFactor.initialValue.ref, "factor:v2:local1");
assert.equal(inlineFactor.initialValue.alias, "InlineFactor");

// Factor-set members carry no library identity → frozen rendering too.
const setMember = shared.factorRowView({
  ref: "factor:v2:m1", alias: "SetMember", factor_set_only: true,
});
assert.equal(setMember.temporary, true, "factor-set members stay viewable inline");

// Plain non-object rows → null (picker falls back to text bubble).
assert.equal(shared.factorRowView(null), null);
assert.equal(shared.factorRowView({alias: "no-ref"}), null);

// Families: library vs transient.
const libraryFamily = shared.familyRowView({
  family_ref: "factor-family:v2:fam1", factor_family_alias: "FamilyA",
});
assert.deepEqual(libraryFamily,
  {kind: "factor_family", ref: "factor-family:v2:fam1", title: "查看因子家族"});
const inlineFamily = shared.familyRowView({
  family_ref: "factor-family:v2:localfam", factor_family_alias: "LocalFam",
  source_origin: "test_inline", temporary: true,
});
assert.equal(inlineFamily.temporary, true);
assert.equal(inlineFamily.initialValue.family_ref, "factor-family:v2:localfam");

// Product groups & categories: library vs test-inline.
assert.deepEqual(shared.productGroupRowView({
  group_ref: "product-group:pg1", name: "中国期货日盘",
}), {kind: "product_group", ref: "product-group:pg1", title: "查看产品组"});
const inlineGroup = shared.productGroupRowView({
  group_ref: "product-group:pglocal", name: "现场组",
  source_origin: "test_inline", temporary: true,
});
assert.equal(inlineGroup.temporary, true);
assert.deepEqual(shared.categoryRowView({
  id: "cat1", title_zh: "分类一",
}), {kind: "category", ref: "cat1", title: "查看产品分类"});
const inlineCategory = shared.categoryRowView({
  id: "catLocal", name: "本地分类", source_kind: "transient",
});
assert.equal(inlineCategory.temporary, true);

// Factor sets.
assert.deepEqual(shared.factorSetRowView({
  target_ref: "set:1", title_zh: "集合一",
}), {kind: "factor_set", ref: "set:1", title: "查看因子集合"});
const inlineSet = shared.factorSetRowView({
  target_ref: "set:local", source_origin: "inline", temporary: true,
});
assert.equal(inlineSet.temporary, true);

console.log("ok");
