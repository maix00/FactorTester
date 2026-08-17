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
};
global.FTTestObjectEditorOverlay = {open: async () => {}};
global.FTBacktestGroupOverrides = {
  render: () => {
    const value = new Element("overrides");
    value.value = () => ({});
    return value;
  },
};
global.FTTestProducts = {
  groupID: value => value?.id || "",
  groupLabel: value => value?.name || value?.id || "",
  projection: value => ({id: value?.id || "", name: value?.name || ""}),
};
global.FTTestFactors = {
  selectedFactor: state => state.factors[0],
};

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
assert.doesNotThrow(() => window.FTBacktestGroupForm.render(
  context, state, {mode: "ls", groupIDs: ["g1", "g2"]}, () => {},
), "opening the Long-Short form must mount picker elements");
console.log("ok");
