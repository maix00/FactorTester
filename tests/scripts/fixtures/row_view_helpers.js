const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

// The row viewer helpers must classify every picker object row by kind and
// route library rows to the ref-based view overlay while test-local rows
// (created inline in a test editor, never persisted) stay viewable through
// their carried frozen value.
class Element {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.className = "";
    this.textContent = "";
    this.title = "";
    this.style = {};
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
}
const body = new Element("body");
global.window = {innerWidth: 1024, innerHeight: 768};
global.document = {
  body,
  createElement: tagName => new Element(tagName),
};
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

// The shared parameter-section header's family "?" is the same nestable view
// overlay (factor_family, mode view) as row viewers — the standalone family
// source-code help overlay is gone.  Library families open by ref; frozen /
// temporary families carry their value so they stay viewable.
const opens = [];
const context = {
  t: value => value,
  openObject: options => { opens.push(options); },
};
const headerIcon = shared.familySourceHelp(context, {
  family_ref: "factor-family:v2:fam9", factor_family_alias: "Family9",
});
assert.equal(headerIcon.className.split(" ").includes("ft-help-icon"), true);
assert.equal(headerIcon.getAttribute("aria-label"), "查看因子家族");
headerIcon.listeners.click({preventDefault() {}, stopPropagation() {}});
assert.deepEqual(opens, [{
  kind: "factor_family", mode: "view", ref: "factor-family:v2:fam9",
}], "the header family link must open the factor-family view overlay by ref");

opens.length = 0;
const frozenHeaderIcon = shared.familySourceHelp(context, {
  factor_family_alias: "InlineFamily",
  source_origin: "test_inline", temporary: true,
  parameter_definitions: [{alias: "N", type: "WindowParam"}],
});
frozenHeaderIcon.listeners.click({preventDefault() {}, stopPropagation() {}});
assert.equal(opens.length, 1, "frozen family header link must open an overlay");
assert.equal(opens[0].kind, "factor_family");
assert.equal(opens[0].mode, "view");
assert.equal(opens[0].temporary, true, "frozen family opens from carried value");
assert.equal(opens[0].initialValue.factor_family_alias, "InlineFamily");

console.log("ok");
