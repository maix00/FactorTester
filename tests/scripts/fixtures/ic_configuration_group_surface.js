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
  ensureProductsForExecution: async (_context, state) => {
    productLoads += 1;
    state.groups = [{group_ref: "product-group:day", name: "日盘产品组"}];
    state.productGroupIndex = new Map(state.groups.map(item => [item.group_ref, item]));
  },
};
window.FTTests = global.FTTests;
let openedObject = null;
global.FTTestObjectEditorOverlay = {
  open: async (_context, options) => { openedObject = options; },
};
window.FTTestObjectEditorOverlay = global.FTTestObjectEditorOverlay;
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
load(`${workbench}/test-content-adapters.js`);
global.FTTestContentAdapters = window.FTTestContentAdapters;
load(`${workbench}/test-setting-chips.js`);
global.FTTestSettingChips = window.FTTestSettingChips;
load(`${workbench}/configuration-groups/common/surface.js`);
global.FTConfigurationGroupSurface = window.FTConfigurationGroupSurface;
load(`${workbench}/configuration-groups/ic/model.js`);
global.FTICConfigurationGroupModel = window.FTICConfigurationGroupModel;
load(`${workbench}/configuration-groups/ic/adapter.js`);

const factorRef = `factor:v2:${"a".repeat(43)}`;
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
  values: {factor_candidates: []},
  savedFactors: [{ref: factorRef, alias: "ROC 1m"}],
  groups: [{
    group_ref: "product-group:day", title_zh: "product-group:day",
    _savedPlaceholder: true,
  }],
  manifest: {
    tab_lists: {"local-settings": [
      {key: "factor", label: "因子执行"},
      {key: "product_path_selection", label: "产品组"},
    ]},
    defaults: {},
    chip_fields: [
      {
        key: "factor_candidates", label: "因子候选",
        chip_template: "因子候选: {factorCandidateLabel}",
        source_keys: ["factorCandidateLabel"], target_tab: "factor",
        source_adapter: "selected_factor_candidates",
        clickable: true,
        detail_overlay: {
          kind_source_key: "factorCandidateDetailKind", mode: "view",
          source_key: "factor_candidate_detail",
          ref_key: "target_ref",
        },
      },
      {
        key: "product_path_selection", label: "产品组",
        chip_template: "产品组: {productPathSelectionLabel}",
        source_keys: ["product_group"], target_tab: "product_path_selection",
        source_adapter: "selected_product_paths",
        value_resolvers: {productPathSelectionLabel: "product_path_selection_label"},
        clickable: true,
        detail_overlay: {kind: "product_group", mode: "view", source_key: "product_group"},
      },
    ],
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

const unresolvedSources = FTTestContentAdapters.chipSources(state, {
  product_path_selection_id: group.product_scope_ref,
});
assert.deepEqual(unresolvedSources.product_group, [],
  "saved placeholders must not expose backend refs as product-group labels");
const rawRefSources = FTTestContentAdapters.chipSources({
  kind: "ic", manifest: state.manifest, values: state.values, groups: [],
}, {product_path_selection_id: group.product_scope_ref});
assert.deepEqual(rawRefSources.product_group, [],
  "unresolved product refs must not render as chip labels");
const chipSources = FTTestContentAdapters.chipSources(state, {
  factor_candidate_refs: [group.factor_ref],
  product_path_selection_id: group.product_scope_ref,
});
assert.equal(chipSources.factorCandidateLabel, "ROC 1m");
assert.equal(chipSources.factorCandidateDetailKind, "factor");
assert.equal(chipSources.factor_candidate_detail.ref, factorRef);
assert.equal(chipSources.factor_candidate_detail.schema_version, 2);

assert.equal(FTConfigurationGroupSurface.renderer("ic"), window.FTICConfigurationGroups);
let root = window.FTICConfigurationGroups.render(context, state, refresh);
assert.deepEqual(state.analysis.configuration_groups[0].editor_mounted_tabs, [
  "__configuration__", "factor", "product_path_selection",
]);
assert.equal(find(root, node => node.tagName === "strong")?.textContent, "IC 配置组");
const displaySettings = find(
  root, node => node.className === "strategy-list-config-toggle",
);
assert.equal(displaySettings?.textContent, "显示设置");
displaySettings.listeners.click();
assert.equal(state.icConfigurationGroupShowConfigOpen, true);
assert.equal(productLoads, 1,
  "opening summary chips must hydrate product labels without previewing a RunSpec");
root = window.FTICConfigurationGroups.render(context, state, refresh);
const hydratedChipSources = FTTestContentAdapters.chipSources(state, {
  factor_candidate_refs: [group.factor_ref],
  product_path_selection_id: group.product_scope_ref,
});
assert.equal(hydratedChipSources.product_group[0].group_ref, group.product_scope_ref);
const chipRow = find(root, node => node.className === "strategy-list-chips");
assert.ok(chipRow);
const renderedChips = [];
(function collect(node) {
  if (String(node.className).split(/\s+/).includes("backend-setting-chip")) {
    renderedChips.push(node);
  }
  for (const child of node.children || []) collect(child);
})(chipRow);
assert.deepEqual(renderedChips.map(chip => (
  chip.children.map(child => child.textContent).join(": ")
)), ["因子候选: ROC 1m", "产品组: 日盘产品组"]);
const factorChip = renderedChips.find(chip => chip.children[0]?.textContent === "因子候选");
factorChip.listeners.click();
assert.deepEqual(
  {kind: openedObject.kind, mode: openedObject.mode, snapshot: openedObject.snapshot},
  {kind: "factor", mode: "view", snapshot: true},
  "a one-factor IC candidate chip must open the factor view overlay",
);
const productChip = renderedChips.find(chip => chip.children[0]?.textContent === "产品组");
productChip.listeners.click();
assert.deepEqual(
  {kind: openedObject.kind, mode: openedObject.mode, ref: openedObject.ref},
  {kind: "product_group", mode: "view", ref: "product-group:day"},
  "IC product-group chip must open the product-group view overlay",
);
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
