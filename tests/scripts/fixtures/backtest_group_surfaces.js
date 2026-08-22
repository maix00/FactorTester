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
  replaceChildren(...nodes) { this.children = [...nodes]; }
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
global.FTBacktestGroupForm = {
  render: (_context, _state, editor) => {
    const form = new Element("form");
    form.dataset.mode = editor.mode;
    return form;
  },
};
global.FTTestSourceUpload = {
  customStrategyPanel: (_context, _state, _refresh, options) => {
    const panel = new Element("section");
    panel.className = "test-custom-strategy-panel";
    panel.textContent = options.title;
    return panel;
  },
};
window.FTTestSourceUpload = global.FTTestSourceUpload;

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
  selected: state => state.analysis.groups.filter(
    item => state.selectedBacktestGroupIDs.includes(item.id),
  ),
  selectedLongShort: state => state.analysis.ls_configs.filter(
    item => state.selectedBacktestLongShortIDs.includes(item.id),
  ),
  groupBatches: state => [{
    key: "batch-1", label: "批次", order: 1,
    items: state.analysis.groups.map(group => ({group, depth: 0})),
  }],
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
  swapLongShort: (state, id) => {
    const item = state.analysis.ls_configs.find(value => value.id === id);
    [item.longGroupId, item.shortGroupId] = [item.shortGroupId, item.longGroupId];
  },
};

vm.runInThisContext(fs.readFileSync(
  require("node:path").join(require("node:path").dirname(process.argv[2]), "configuration-groups/common/surface.js"),
  "utf8",
), {filename: "configuration-groups/common/surface.js"});
global.FTConfigurationGroupSurface = window.FTConfigurationGroupSurface;

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
    surfaces: [
      {
        key: "groups", label: "分组", mount: "group-settings", kind: "list",
        order: 1, selection: "multi", item_label: "分组",
        content_adapter: "backtest_groups",
      },
      {
        key: "arbitrary-book", label: "组合簿", mount: "group-settings", kind: "list",
        order: 2, selection: "single", item_label: "组合",
        content_adapter: "backtest_long_short",
      },
      {
        key: "custom_strategy", label: "自定义策略", mount: "group-settings", kind: "list",
        order: 3, selection: "single", item_label: "自定义策略",
        content_adapter: "backtest_custom_strategies",
        content_options: {inputs: [{kind: "strategy_source"}]},
      },
    ],
    flows: [
      {
        surface: "groups", key: "add_group", label: "新增分组",
        kind: "create", order: 1,
      },
      {
        surface: "groups", key: "create_ls", label: "创建 Long-Short 组合",
        kind: "compose", order: 2, min_selected: 2, max_selected: 2,
      },
      {
        surface: "arbitrary-book", key: "add_long_short", label: "新增 Long-Short 组合",
        kind: "create", order: 1,
      },
      {
        surface: "arbitrary-book", key: "swap_long_short", label: "交换多空",
        kind: "swap", order: 2, min_selected: 1, max_selected: 1,
      },
      {
        surface: "arbitrary-book", key: "not-a-hardcoded-key", label: "移除",
        kind: "delete", order: 3, min_selected: 1,
      },
    ],
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
const tabButton = find(root, node => node.className.includes("tab-chip-button"));
assert.ok(tabButton, "surface tabs should be rendered by the shared tab component");
const surfaceTabs = findAll(root, node => node.className.includes("tab-chip-button"));
assert.equal(surfaceTabs.length, 3, "strategy settings must expose three peer surfaces");
surfaceTabs[1].listeners.click();
assert.equal(state.backtestGroupSurfaceKey, "arbitrary-book");
assert.ok(find(root, node => node.tagName === "button"
  && node.textContent === "新增 Long-Short 组合"),
  "switching strategy surfaces must immediately replace the action bar");
state.backtestGroupSurfaceKey = "custom_strategy";
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
assert.ok(find(root, node => node.className === "test-custom-strategy-panel"),
  "custom strategies must render inside the strategy-group surface");
state.backtestGroupSurfaceKey = "groups";
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
const addGroup = find(root, node => node.tagName === "button" && node.textContent === "新增分组");
assert.ok(addGroup, "the backend create flow should render an add-group action");
addGroup.listeners.click();
assert.equal(state.backtestGroupEditor.mode, "base",
  "clicking add-group must open the base-group editor");
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
assert.equal(find(root, node => node.tagName === "form").dataset.mode, "base",
  "the add-group action must mount the editor form");
state.backtestGroupEditor = null;

const createLongShort = find(
  root, node => node.tagName === "button" && node.textContent === "创建 Long-Short 组合",
);
assert.ok(createLongShort, "the compose flow should render from the backend declaration");
assert.equal(createLongShort.disabled, true,
  "Long-Short creation must stay disabled until two groups are selected");
state.selectedBacktestGroupIDs = ["g1", "g2"];
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
const enabledCompose = find(
  root, node => node.tagName === "button" && node.textContent === "创建 Long-Short 组合",
);
assert.equal(enabledCompose.disabled, false);
enabledCompose.listeners.click();
assert.deepEqual(state.backtestGroupEditor, {mode: "ls", groupIDs: ["g1", "g2"]},
  "composing two selected groups must open the Long-Short editor");
state.backtestGroupEditor = null;

state.backtestGroupSurfaceKey = "arbitrary-book";
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
const addLongShort = find(
  root, node => node.tagName === "button" && node.textContent === "新增 Long-Short 组合",
);
assert.ok(addLongShort, "the Long-Short surface must expose its own create action");
addLongShort.listeners.click();
assert.equal(state.backtestGroupEditor.mode, "ls",
  "clicking add Long-Short must open the Long-Short editor");
state.backtestGroupEditor = null;

state.backtestGroupSurfaceKey = "groups";
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
const groupsTab = find(root, node => node.className.includes("tab-chip-button")
  && node === findAll(root, node => node.className.includes("tab-chip-button"))[0]);
groupsTab.listeners.click();
assert.equal(state.backtestGroupSurfaceKey, null,
  "clicking the active surface tab should close its content");
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
const closedHost = find(root, node => node.className.includes("backtest-group-host"));
assert.equal(closedHost.children[0].hidden, true,
  "a closed surface tab must stay closed after its parent rerenders");
const reopenedButton = find(root, node => node.className.includes("tab-chip-button")
  && node === findAll(root, node => node.className.includes("tab-chip-button"))[0]);
reopenedButton.listeners.click();
assert.equal(state.backtestGroupSurfaceKey, "groups",
  "clicking a closed surface tab should reopen its content");
state.backtestGroupSurfaceKey = "arbitrary-book";
root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
let selection = find(root, node => node.tagName === "input");
assert.equal(selection.type, "radio", "backend single-selection controls the input type");
selection.checked = true;
selection.listeners.change();
assert.deepEqual(state.selectedBacktestLongShortIDs, ["ls1"]);

root = window.FTBacktestGroups.render(context, state, () => { refreshCount += 1; });
const swap = find(root, node => node.tagName === "button" && node.textContent === "交换多空");
assert.ok(swap, "the Long-Short row must expose its declared swap action");
swap.listeners.click();
assert.deepEqual(
  state.analysis.ls_configs[0],
  {id: "ls1", name: "组合", longGroupId: "g2", shortGroupId: "g1"},
  "swapping a Long-Short row must update the persisted legs",
);
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

function findAll(node, predicate, result = []) {
  if (predicate(node)) result.push(node);
  for (const child of node.children || []) findAll(child, predicate, result);
  return result;
}
