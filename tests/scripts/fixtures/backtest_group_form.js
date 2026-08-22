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
global.FTTestObjectEditorOverlay = {open: async () => {}};
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
};
window.FTTestFactorCandidateSources = global.FTTestFactorCandidateSources;

const groups = [
  {id: "g1", name: "第一组"},
  {id: "g2", name: "第二组"},
];
global.FTBacktestGroupModel = {
  find: (_state, id) => groups.find(item => item.id === id),
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
  analysis: {groups: [], ls_configs: []},
  groups,
  factors: [{alias: "ROC"}],
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
assert.doesNotThrow(() => window.FTBacktestGroupForm.render(
  context, state, {mode: "ls", groupIDs: ["g1", "g2"]}, () => {},
), "opening the Long-Short form must mount picker elements");
console.log("ok");
