const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
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

function load(file) {
  vm.runInThisContext(fs.readFileSync(file, "utf8"), {filename: path.basename(file)});
}
function find(root, predicate) {
  if (predicate(root)) return root;
  for (const child of root.children || []) {
    const result = find(child, predicate);
    if (result) return result;
  }
  return null;
}

global.window = {};
global.document = {createElement: tag => new Element(tag)};
global.confirm = () => true;
global.FTUI = {
  empty: (title, copy) => {
    const node = new Element("empty"); node.textContent = `${title}: ${copy}`; return node;
  },
};
global.FTTestProducts = {groupID: value => value?.group_ref || value?.id || ""};
let factorLoads = 0;
let productLoads = 0;
global.FTTests = {
  ensureFactorsForExecution: async () => { factorLoads += 1; },
  ensureProductsForExecution: async () => { productLoads += 1; },
};
window.FTTests = global.FTTests;
global.FTICConfigurationGroupForm = {
  render: (_context, _state, editor) => {
    const form = new Element("form");
    form.dataset.mode = editor.mode;
    form.dataset.groupID = editor.groupID || "";
    return form;
  },
};

global.structuredClone = global.structuredClone
  || (value => JSON.parse(JSON.stringify(value)));
const workbench = "server/manager/web/workbench";
load(`${workbench}/tab-chip-content.js`);
global.FTTabChipContent = window.FTTabChipContent;
load(`${workbench}/tab-list-chip.js`);
global.FTTabListChip = window.FTTabListChip;
load(`${workbench}/strategy-list.js`);
global.FTStrategyList = window.FTStrategyList;
load(`${workbench}/configuration-groups/common/surface.js`);
global.FTConfigurationGroupSurface = window.FTConfigurationGroupSurface;
load(`${workbench}/configuration-groups/ic/model.js`);
global.FTICConfigurationGroupModel = window.FTICConfigurationGroupModel;
load(`${workbench}/configuration-groups/ic/adapter.js`);

const factorRef = "factor:v1:profile-max:path:roc:commit:blob";
const group = {
  config_group_id: "icg-day",
  batch_id: "icb-day",
  name: "日盘 ROC",
  factor_ref: factorRef,
  product_scope_ref: "product-group:day",
  entry_delay_bars: 0,
  horizon: {sampling: "scale_aware"},
  methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
};
const state = {
  kind: "ic",
  analysis: {configuration_groups: [group]},
  selectedICConfigurationGroupIDs: [],
  manifest: {
    surfaces: [{
      key: "ic_configs", label: "配置组设置", mount: "group-settings",
      kind: "list", selection: "single", item_label: "配置组",
      content_adapter: "ic_configuration_groups",
    }],
    flows: [
      {surface: "ic_configs", key: "add_config", label: "新增配置组", kind: "create"},
      {surface: "ic_configs", key: "edit", label: "编辑", kind: "edit", min_selected: 1, max_selected: 1},
      {surface: "ic_configs", key: "delete", label: "删除", kind: "delete", min_selected: 1},
    ],
  },
};
let refreshCount = 0;
const context = {
  t: value => value,
  button(label, action) {
    const button = new Element("button");
    button.textContent = label;
    button.listeners.click = action;
    return button;
  },
};
const refresh = () => { refreshCount += 1; };

assert.equal(FTConfigurationGroupSurface.renderer("ic"), window.FTICConfigurationGroups);
let root = window.FTICConfigurationGroups.render(context, state, refresh);
assert.deepEqual(state.analysis.configuration_groups[0].editor_mounted_tabs, [
  "__configuration__", "factor", "product_path_selection",
]);
assert.equal(find(root, node => node.tagName === "strong")?.textContent, "IC 配置组");
const selection = find(root, node => node.tagName === "input");
assert.equal(selection.type, "radio");
selection.checked = true;
selection.listeners.change();
assert.deepEqual(state.selectedICConfigurationGroupIDs, ["icg-day"]);

root = window.FTICConfigurationGroups.render(context, state, refresh);
const edit = find(root, node => node.tagName === "button" && node.textContent === "编辑");
assert.equal(edit.disabled, false);
edit.listeners.click();
assert.deepEqual(state.icConfigurationGroupEditor, {mode: "edit", groupID: "icg-day"});
awaitTick();
root = window.FTICConfigurationGroups.render(context, state, refresh);
const editForm = find(root, node => node.tagName === "form");
assert.equal(editForm.dataset.mode, "edit");
assert.equal(editForm.dataset.groupID, "icg-day");

root = window.FTICConfigurationGroups.render(context, state, refresh);
const remove = find(root, node => node.tagName === "button" && node.textContent === "删除");
remove.listeners.click();
assert.deepEqual(state.analysis.configuration_groups, []);
assert.deepEqual(state.selectedICConfigurationGroupIDs, []);
assert.equal(state.icConfigurationGroupEditor, null);

state.icConfigurationGroupEditor = {mode: "edit", groupID: "icg-stale"};
root = window.FTICConfigurationGroups.render(context, state, refresh);
assert.equal(state.icConfigurationGroupEditor, null, "a stale open editor must be discarded");
assert.equal(find(root, node => node.tagName === "form"), null);

root = window.FTICConfigurationGroups.render(context, state, refresh);
const create = find(root, node => node.tagName === "button" && node.textContent === "新增配置组");
create.listeners.click();
assert.deepEqual(state.icConfigurationGroupEditor, {mode: "create"});
awaitTick();
root = window.FTICConfigurationGroups.render(context, state, refresh);
assert.equal(find(root, node => node.tagName === "form").dataset.mode, "create");
assert.ok(refreshCount >= 4);
assert.ok(factorLoads >= 2);
assert.ok(productLoads >= 2);

console.log("ok");

function awaitTick() {
  // onEditorOpened starts catalog promises without blocking the surface action;
  // the synchronous model/editor state is the contract exercised here.
}
