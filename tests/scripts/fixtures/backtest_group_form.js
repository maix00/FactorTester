const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.type = "";
    this.rows = 0;
    this.style = {setProperty: () => {}};
    this.classList = {add: () => {}};
  }

  append(...nodes) {
    for (const node of nodes) {
      assert.ok(node instanceof Element, `non-DOM value appended to ${this.tagName}`);
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }

  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  querySelector() { return null; }
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
global.FTUI = {empty: () => new Element("empty")};
global.FTTestFieldRow = {
  create: (_label, control) => {
    const row = new Element("field-row");
    row.append(control);
    return row;
  },
};
global.FTTestObjectPicker = {
  create: () => ({element: new Element("picker"), setValues: () => {}}),
  lazyLoading: (state, key) => {
    const status = String(state?.lazy?.[key]?.status || "");
    return Boolean(status && status !== "ready" && status !== "error");
  },
};
global.FTTestChoicePicker = {
  create: () => ({element: new Element("choice"), values: []}),
};
global.FTObjectOverlay = {open: async () => {}};
global.FTBacktestGroupOverrides = {
  render: () => {
    const value = new Element("overrides");
    value.value = () => ({});
    return value;
  },
};
let sharedProductPanels = 0;
let sharedFactorPickers = 0;
let sharedFactorPanels = 0;
let sharedFactorPanelUpdates = 0;
let factorPickerOptions;
let factorScopeSource = "outer";
let scopedSourceInitial;
let tabOptions;
let chipSourceItem;
global.FTStrategyEditorTabs = {
  create: options => {
    tabOptions = options;
    return Object.assign(new Element("shared-editor-tabs"), {
      refreshChips: () => {},
      value: () => ({mountedTabs: []}),
    });
  },
};
window.FTStrategyEditorTabs = global.FTStrategyEditorTabs;
global.FTTestContentAdapters = {
  chipSources: (_state, item) => { chipSourceItem = item; return {}; },
};
window.FTTestContentAdapters = global.FTTestContentAdapters;
global.FTTestProducts = {
  groupID: value => value?.id || "",
  groupLabel: value => value?.name || value?.id || "",
  projection: value => ({id: value?.id || "", name: value?.name || ""}),
  selectionPanel: () => {
    sharedProductPanels += 1;
    return new Element("shared-product-selection");
  },
};
global.FTTestFactors = {
  selectedFactor: state => state.factors[0],
};
global.FTTestFactorCandidateSources = {
  candidatePicker: (_context, _state, options) => {
    sharedFactorPickers += 1;
    factorPickerOptions = options;
    return {element: new Element("shared-factor-picker"), values: options.selected || []};
  },
  innerPanel: () => {
    sharedFactorPanels += 1;
    const panel = new Element("shared-factor-panel");
    panel.update = () => { sharedFactorPanelUpdates += 1; };
    return panel;
  },
  scopedSourceState: (_state, _owner, initial) => {
    scopedSourceInitial = initial;
    return {values: {factor_candidates: []}};
  },
  scopedSourceSnapshot: local => ({
    factor_candidate_refs: (local.values.factor_candidates || []).map(item => item.ref),
    factor_candidates: local.values.factor_candidates || [],
    factor_source_selections: [], factor_set_selections: [],
  }),
  scopedSourcePanel: () => new Element("shared-factor-source-panel"),
};
window.FTTestFactorCandidateSources = global.FTTestFactorCandidateSources;
global.FTStrategyEditorScope = {
  scope: (state, kind) => kind === "factor"
    ? {items: state.factors, required: false, ready: true, source: factorScopeSource}
    : {items: state.groups, required: false, ready: true, source: "visible"},
  inlineCreateAllowed: () => true,
  fieldVisible: () => false,
  validate: () => [],
};
window.FTStrategyEditorScope = global.FTStrategyEditorScope;

const groups = [
  {id: "g1", name: "第一组"},
  {id: "g2", name: "第二组"},
];
global.FTBacktestGroupModel = {
  find: (current, id) => current.analysis.groups.find(item => item.id === id)
    || groups.find(item => item.id === id),
  groupLabel: value => value?.name || value?.id || "",
  rootsAndChildren: () => groups.map(group => ({group})),
  registeredOverrides: () => ({}),
  addBaseBatch: () => {},
  addDerived: () => {},
  updateGroup: () => {},
  addLongShort: () => {},
  updateLongShort: () => {},
  renameGroup: () => {},
  renameLongShort: () => {},
};
window.FTBacktestGroupModel = global.FTBacktestGroupModel;

vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-group-form.js",
});
if (process.argv[3]) {
  vm.runInThisContext(fs.readFileSync(process.argv[3], "utf8"), {
    filename: "strategy-editor-pickers.js",
  });
}

const context = {
  session: null,
  t: value => value,
  button: (label, action) => {
    const button = new Element("button");
    button.textContent = label;
    button.addEventListener("click", action);
    return button;
  },
};
const state = {
  analysis: {groups: [], ls_configs: [], factor_strategy_bindings: []},
  groups,
  factors: [{ref: "factor:v2:roc", alias: "ROC"}],
  values: {split_count: 5, group_index: 1},
  manifest: {defaults: {}},
  groupRef: "g1",
};

assert.doesNotThrow(() => window.FTBacktestGroupForm.render(
  context, state, {mode: "base"}, () => {},
), "opening the base-group form must mount picker elements");
tabOptions.renderProduct();
assert.equal(sharedProductPanels, 1,
  "the nested product tab must use the outer shared product selection renderer");
assert.equal(sharedFactorPickers, 1,
  "the nested factor tab must use the shared factor candidate picker");
assert.equal(sharedFactorPanels, 1,
  "the nested factor tab must mount the shared factor panel once");
factorPickerOptions.onChange(["ROC"]);
assert.equal(sharedFactorPanels, 1,
  "changing a factor must not replace the shared picker panel during its click event");
assert.equal(sharedFactorPanelUpdates, 1,
  "changing a factor must update only dependent shared factor fields");
tabOptions.chipSources();
assert.deepEqual(chipSourceItem.factor_candidate_refs, ["ROC"],
  "backtest chip sources use the selected factor references");
assert.equal(chipSourceItem.product_path_selection_id, "g1",
  "backtest chip sources use the selected product group");
factorScopeSource = "visible";
state.values.factor_candidates = [{ref: "factor:v2:sibling", alias: "Sibling"}];
assert.doesNotThrow(() => window.FTBacktestGroupForm.render(
  context, state, {mode: "base"}, () => {},
), "an unmounted outer factor tab must render the local source builder");
assert.deepEqual(scopedSourceInitial.factor_candidate_refs, [],
  "a new strategy must not inherit another strategy or the global primary factor");
assert.doesNotThrow(() => window.FTBacktestGroupForm.render(
  context, state, {mode: "ls", groupIDs: ["g1", "g2"]}, () => {},
), "opening the Long-Short form must mount picker elements");

state.strategyFamilyCatalog = {
  families: [{
    family_ref: "family:group", family_revision_ref: "family-rev:1",
    name: "因子横截面分组", strategy_refs: ["strategy:group"],
  }],
  items: [{
    object_kind: "strategy", family_ref: "family:group",
    template_ref: "strategy:group", revision_ref: "strategy-rev:1",
    strategy_ref: "strategy:group", strategy_revision_ref: "strategy-rev:1",
    name: "因子横截面分组第 N 组",
    configuration_schema: {schema_ref: "schema:1", fields: [
      {key: "signal", label: "分组因子", type: "factor_ref", required: true},
      {key: "product_group_ref", label: "产品组", type: "product_group_ref", required: true},
      {key: "split_count", label: "分组数", type: "integer", required: true, default: 5, minimum: 2},
      {key: "group_index", label: "分组序数", type: "integer", required: true, default: 1, minimum: 1, maximum_from: "split_count"},
    ]},
  }],
};
const familyForm = window.FTBacktestGroupForm.render(
  context, state, {mode: "family"}, () => {},
);
function findByLabel(root, label) {
  if (root["aria-label"] === label) return root;
  for (const child of root.children || []) {
    const found = findByLabel(child, label);
    if (found) return found;
  }
  return null;
}
function findButton(root, label) {
  if (root.tagName === "button" && root.textContent === label) return root;
  for (const child of root.children || []) {
    const found = findButton(child, label);
    if (found) return found;
  }
  return null;
}
assert.ok(findByLabel(familyForm, "策略家族"));
assert.ok(findByLabel(familyForm, "策略实现"));
assert.ok(findByLabel(familyForm, "分组因子"));
assert.ok(findByLabel(familyForm, "产品组"));
assert.ok(findByLabel(familyForm, "分组数"));
assert.ok(findByLabel(familyForm, "分组序数"));
findByLabel(familyForm, "分组因子").value = "factor:v2:roc";
findByLabel(familyForm, "产品组").value = "g1";
findButton(familyForm, "保存").listeners.click();
assert.equal(state.analysis.groups.length, 1);
assert.deepEqual(state.analysis.groups[0].parameters, {split_count: 5, group_index: 1});
assert.equal(state.analysis.groups[0].product_group_ref, "g1");
assert.deepEqual(state.analysis.factor_strategy_bindings[0].factor_bindings, {
  signal: "factor:v2:roc",
});
assert.equal(state.analysis.factor_strategy_bindings[0].family_revision_ref, "family-rev:1");

state.strategyFamilyCatalog.families.push({
  family_ref: "nautilus-strategy-family:user-authored",
  family_revision_ref: "nautilus-strategy-family-revision:user-authored:1",
  name: "用户策略", strategy_refs: ["strategy:user"],
});
state.strategyFamilyCatalog.items.push({
  object_kind: "strategy", library_kind: "nautilus_strategy_source",
  family_ref: "nautilus-strategy-family:user-authored",
  strategy_ref: "strategy:user", current_revision_ref: "strategy-revision:r2",
  revision_ref: "strategy-revision:r2", name: "My Nautilus Strategy",
  source_sha256: "abc123",
  current_revision: {source_sha256: "abc123"},
  configuration_schema: {schema_ref: "strategy-revision:r2:configuration-schema:1", fields: [
    {key: "product_group_ref", label: "产品组", type: "product_group_ref", required: true},
  ]},
});
const libraryForm = window.FTBacktestGroupForm.render(
  context, state, {mode: "family"}, () => {},
);
findByLabel(libraryForm, "策略家族").value = "nautilus-strategy-family:user-authored";
findByLabel(libraryForm, "策略家族").listeners.change();
findByLabel(libraryForm, "产品组").value = "g2";
findButton(libraryForm, "保存").listeners.click();
assert.equal(state.analysis.groups.length, 2);
assert.equal(state.analysis.groups[1].strategy_kind, "library");
assert.equal(state.analysis.groups[1].strategy_revision_ref, "strategy-revision:r2");
assert.equal(state.strategyBindings[0].target_strategy_id, state.analysis.groups[1].id);
assert.equal(state.strategyBindings[0].source.strategy_ref, "strategy:user");
assert.equal(state.strategyBindings[0].source.revision_ref, "strategy-revision:r2");
assert.equal(state.strategyBindings[0].source.source_sha256, "abc123");
assert.equal(state.analysis.factor_strategy_bindings.length, 1,
  "adding a user strategy must not leave a stale factor-template binding");
const editLibraryForm = window.FTBacktestGroupForm.render(
  context, state, {mode: "edit", groupID: state.analysis.groups[1].id}, () => {},
);
assert.ok(findByLabel(editLibraryForm, "策略家族"),
  "editing a library strategy must keep the family-driven configuration form");
assert.equal(findByLabel(editLibraryForm, "产品组").value, "g2");
console.log("ok");
