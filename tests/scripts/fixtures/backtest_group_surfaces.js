const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.dataset = {};
    this.checked = false;
    this.disabled = false;
    this.open = false;
    this.hidden = false;
    this.textContent = "";
    this.style = {setProperty: () => {}};
    this.classList = {
      add: (...names) => { this.className = `${this.className} ${names.join(" ")}`.trim(); },
      toggle: (name, enabled) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled) names.add(name); else names.delete(name);
        this.className = [...names].join(" ");
      },
    };
  }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
global.confirm = () => true;
global.FTUI = {
  empty: (title, copy) => {
    const node = new Element("empty"); node.textContent = `${title}: ${copy}`; return node;
  },
  table: () => ({shell: new Element("table"), body: new Element("tbody")}),
  appendRow: () => {},
};
global.FTTestProducts = {groupLabel: () => "", groupID: () => ""};
global.FTBacktestGroupForm = {render: () => new Element("form")};

vm.runInThisContext(fs.readFileSync(
  require("node:path").join(require("node:path").dirname(process.argv[2]), "tab-chip-content.js"),
  "utf8",
), {filename: "tab-chip-content.js"});
global.FTTabChipContent = window.FTTabChipContent;
vm.runInThisContext(fs.readFileSync(
  require("node:path").join(require("node:path").dirname(process.argv[2]), "tab-list-chip.js"),
  "utf8",
), {filename: "tab-list-chip.js"});
global.FTTabListChip = window.FTTabListChip;

vm.runInThisContext(fs.readFileSync(
  require("node:path").join(require("node:path").dirname(process.argv[2]), "strategy-list.js"),
  "utf8",
), {filename: "strategy-list.js"});
global.FTStrategyList = window.FTStrategyList;

let removed = false;
global.FTBacktestGroupModel = {
  initialize: state => state.analysis,
  selected: () => [],
  selectedLongShort: state => state.analysis.ls_configs.filter(
    item => state.selectedBacktestLongShortIDs.includes(item.id),
  ),
  rootsAndChildren: () => [],
  groupLabel: group => group?.name || "",
  find: (state, id) => state.analysis.groups.find(group => group.id === id),
  registeredOverrides: () => ({}),
  toggle: () => {},
  toggleLongShort: (state, id, checked, selection) => {
    assert.equal(selection, "single");
    state.selectedBacktestLongShortIDs = checked ? [id] : [];
  },
  removeSelected: () => {},
  removeSelectedLongShort: state => {
    removed = true;
    state.analysis.ls_configs = [];
    state.selectedBacktestLongShortIDs = [];
  },
};

vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-groups.js",
});

const state = {
  kind: "backtest",
  analysis: {
    groups: [{id: "g1", name: "第一组"}, {id: "g2", name: "第二组"}],
    ls_configs: [{id: "ls1", name: "组合", longGroupId: "g1", shortGroupId: "g2"}],
  },
  selectedBacktestGroupIDs: [],
  selectedBacktestLongShortIDs: [],
  manifest: {
    surfaces: [{
      key: "arbitrary-book", label: "组合簿", mount: "group-settings", kind: "list",
      order: 1, selection: "single", item_label: "组合",
      content_adapter: "backtest_long_short",
    }],
    flows: [{
      surface: "arbitrary-book", key: "not-a-hardcoded-key", label: "移除",
      kind: "delete", order: 1, min_selected: 1,
    }],
  },
};
let refreshCount = 0;
const context = {
  t: value => value,
  button: (label, action) => {
    const button = new Element("button");
    button.textContent = label; button.listeners.click = action; return button;
  },
};

let root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
let selection = find(root, node => node.tagName === "input");
assert.equal(selection.type, "radio", "backend single-selection controls the input type");
selection.checked = true;
selection.listeners.change();
assert.deepEqual(state.selectedBacktestLongShortIDs, ["ls1"]);

root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
const remove = find(root, node => node.tagName === "button" && node.textContent === "移除");
assert.ok(remove, "a flow with an arbitrary key is rendered from its surface declaration");
assert.equal(remove.disabled, false);
remove.listeners.click();
assert.equal(removed, true);
assert.deepEqual(state.analysis.ls_configs, []);
assert.ok(refreshCount >= 2);
console.log("ok");

function find(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const result = find(child, predicate);
    if (result) return result;
  }
  return null;
}
