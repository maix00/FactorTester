const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = value => JSON.parse(JSON.stringify(value));

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.title = "";
    this.type = "";
    this.attributes = {};
    this.classList = {toggle() {}};
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}

global.document = {createElement: tagName => new Element(tagName)};
global.FTUI = {
  loading: () => new Element("loading"),
  empty: () => new Element("empty"),
};
let factorPanelCalls = 0;
global.FTTestFactors = {panel: () => {
  factorPanelCalls += 1;
  return new Element("factor-panel");
}};
global.FTTestFactorSelection = {
  factorAlias: value => value?.alias || "",
  candidates: state => state.values?.factor_candidates || [],
};
window.FTTestFactorSelection = global.FTTestFactorSelection;
global.FTICHorizonSettings = {normalizeSettingValues: (_manifest, values) => values};
for (const path of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
  for (const name of [
    "FTSettingRules", "FTTestSettingChips", "FTTabChipContent",
    "FTTestContentAdapters", "FTTestSettings", "FTMultiSelectFilter",
    "FTTestObjectPicker", "FTTestChoicePicker", "FTTestFieldRow",
  ]) {
    if (window[name]) global[name] = window[name];
  }
}

const manifest = {
  settings_sections: [{key: "scope", label: "研究对象", description: "先选对象", order: 10}],
  tab_lists: {"local-settings": [
    {key: "factor", label: "因子", section_key: "scope", content_adapter: "factor_selection"},
    {key: "products", label: "产品路径", section_key: "scope", content_adapter: "product_path_selection"},
    {key: "time", label: "时间范围", section_key: "scope"},
    {key: "advanced", label: "高级", section_key: "scope"},
    {key: "group_strategy", label: "分组策略", section_key: "scope"},
  ]},
  defaults: {
    start_date: {
      tab_key: "time", label: "开始日期", chip_template: "开始日期: {value}",
      value_descriptor: {editor: "date", options: []}, value: "", serialization: {},
    },
    hidden_default: {
      tab_key: "advanced", label: "隐藏条件字段", chip_template: "隐藏条件字段: {value}",
      value_descriptor: {editor: "text", options: []}, value: "default", serialization: {},
      rules: {visible_if: {mode: ["advanced"]}},
    },
  },
  chip_fields: [{
    key: "factor_alias", label: "因子", chip_template: "因子: {factorAlias}",
    source_keys: ["factorAlias"], value_resolvers: {}, target_tab: "factor",
  }, {
    key: "strategy_identity", label: "策略分组",
    chip_template: "策略分组: {n_groups}",
    source_keys: ["n_groups"], value_resolvers: {}, target_tab: "group_strategy",
    display_scope: "strategy",
  }],
};

// The settings shell must remain renderable while the shared field-control
// implementation is still being fetched.  Only the active panel requests it;
// chips and the tab bar do not pull the control code into the initial pass.
const deferredFields = window.FTTestSettingFields;
delete window.FTTestSettingFields;
let requestedFieldCode = 0;
const deferred = FTTestSettings.render(manifest, {start_date: "2025-01-02"}, {
  t: value => value,
}, {
  activeTab: "factor", mountedTabs: ["factor", "time"],
    chipSources: {factorAlias: ["ROC 1m"], n_groups: 5},
  lazyState: () => ({status: "ready"}),
  ensureSettingsFieldsCode: () => { requestedFieldCode += 1; },
});
assert.equal(requestedFieldCode, 1, "active settings panel should request field code");
assert.equal(
  deferred.children[2].children[0].children[0].children[0].tagName,
  "loading",
);
window.FTTestSettingFields = deferredFields;

function render(factorAlias, onChipOpen) {
  return FTTestSettings.render(manifest, {start_date: "2025-01-02"}, {
    t: value => value,
  }, {
    activeTab: "factor",
    mountedTabs: ["factor", "time"],
    chipSources: {factorAlias: [factorAlias], n_groups: 5},
    lazyState: () => ({status: "ready"}),
    onTabChange: onChipOpen,
  });
}

const initial = FTTestSettings.initialValues(manifest, {
  start_date: "saved",
  hidden_default: "stale",
}, ["time"]);
assert.equal(initial.start_date, "saved");
assert.equal(initial.hidden_default, "default");

let opened = "";
const first = render("ROC 1m", tabKey => { opened = tabKey; });
assert.equal(factorPanelCalls, 1, "the active ready tab should load its adapter");
assert.deepEqual(first.children.map(item => item.className), [
  "backend-settings-tab-bar",
  "test-settings-current",
  "backend-settings-host",
]);
assert.ok(first.children[0].children.every(button => button.children.length === 1),
  "test setting tabs should render only their title");
assert.equal(first.children[0].children[0].children[0].textContent, "因子");
const chipRow = first.children[1].children[1];
const factorGroup = chipRow.children.find(item => item.className === "backend-settings-chip-group");
assert.ok(factorGroup, "tab-based chip group should be present");
const factorChip = factorGroup.children.find(item => item.className.includes("backend-setting-chip"));
assert.equal(factorChip.children[1].textContent, "ROC 1m");
assert.equal(
  chipRow.children.some(group => group.textContent.includes("策略分组")), false,
  "strategy-scoped chips must not enter the shared settings summary",
);
const host = first.children[2];
assert.equal(host.children[1].children.length, 0,
  "inactive settings tabs should not render their content on first load");
assert.equal(host.children[2].children.length, 0,
  "the settings manager should be lazy until its tab is opened");
first.children[0].children[1].listeners.click();
factorChip.listeners.click();
assert.equal(opened, "factor");
assert.equal(host.children[0].hidden, false,
  "clicking a chip for an inactive tab should open its content");
factorChip.listeners.click();
assert.equal(host.children[0].hidden, true,
  "clicking the active chip should collapse its tab content");
first.children[0].children[0].listeners.click();
assert.equal(host.children[0].hidden, false,
  "clicking a collapsed tab should reopen its content");
first.children[0].children[0].listeners.click();
assert.equal(host.children[0].hidden, true,
  "clicking the active tab again should collapse its content");
const closed = FTTestSettings.render(manifest, {start_date: "2025-01-02"}, {
  t: value => value,
}, {
  activeTab: null, mountedTabs: ["factor", "time"],
  chipSources: {factorAlias: ["ROC 1m"], n_groups: 5}, lazyState: () => ({status: "ready"}),
});
assert.equal(closed.children[2].children[0].hidden, true,
  "an explicit closed tab state should stay closed after settings rerender");
const manageButton = first.children[0].children[first.children[0].children.length - 1];
manageButton.listeners.click();
const managePanel = host.children[host.children.length - 1];
const manager = managePanel.children[0];
const managerList = manager.children[0];
const timeRow = managerList.children.find(item => item.className === "test-settings-manager-row"
  && item.children[1].children[0].children[0].textContent === "时间范围");
assert.ok(timeRow, "+ 设置 content should list every tab");
assert.ok(timeRow.children[1].children[1].children.length >= 1,
  "+ 设置 content should show default chips");
const defaultGroup = timeRow.children[1].children[1].children[0];
const defaultChip = defaultGroup.children.find(item => item.className.includes("backend-setting-chip"));
assert.equal(defaultChip.children[1].textContent, "未设置（默认）");
const productRow = managerList.children.find(item => item.className === "test-settings-manager-row"
  && item.children[1].children[0].children[0].textContent === "产品路径");
assert.ok(productRow, "content-only tabs should still have an aligned default row");
const productDefaultGroup = productRow.children[1].children[1];
const productChip = productDefaultGroup.children
  .flatMap(group => group.children)
  .find(item => item.className.includes("backend-setting-chip"));
assert.ok(productChip, "content-only tabs should render a default chip");
assert.equal(productChip.children[1].textContent, "未设置（默认）");

const overlayManifest = {
  chip_fields: [
    {
      source_adapter: "selected_factor_candidates",
      source_keys: ["factorCandidateLabel"],
      detail_overlay: {source_key: "factor_candidates"},
    },
    {
      source_adapter: "selected_factors", source_keys: ["factorRef", "factorLabel"],
      detail_overlay: {source_key: "factor"},
    },
    {
      source_adapter: "selected_product_paths", source_keys: ["product_path_selection"],
      detail_overlay: {source_key: "product_group"},
    },
  ],
};
const factorRefs = {
  roc: `factor:v2:${"a".repeat(43)}`,
  value: `factor:v2:${"b".repeat(43)}`,
  value1: `factor:v2:${"c".repeat(43)}`,
  value2: `factor:v2:${"d".repeat(43)}`,
  first: `factor:v2:${"e".repeat(43)}`,
  second: `factor:v2:${"f".repeat(43)}`,
  history: `factor:v2:${"g".repeat(43)}`,
};
const adapterSources = FTTestContentAdapters.chipSources({
  kind: "backtest", manifest: overlayManifest,
  values: {factor_candidates: [
    {ref: factorRefs.roc, alias: "ROC 1m"},
    {ref: factorRefs.value, alias: "Value",
      factor_set_refs: ["factor-set:value"], factor_set_only: true},
  ], factor_source_selections: [
    {ref: factorRefs.roc, alias: "ROC 1m"},
  ], factor_set_selections: [
    {target_ref: "factor-set:value", title_zh: "价值集合"},
  ]},
  groups: [{group_ref: "group:day", name: "日盘"}],
}, {
  factor_candidate_refs: [factorRefs.roc],
  product_path_selection: {product_group_template_id: "group:day", label: "日盘"},
});
assert.equal(adapterSources.factor[0].ref, factorRefs.roc);
assert.equal(adapterSources.factorCandidateLabel, "ROC 1m");
assert.equal(adapterSources.factor_candidates.length, 1);
assert.equal(adapterSources.factor_candidates[0].temporary, true);
assert.deepEqual(adapterSources.factor_candidates[0].related_references, [{
  target_ref: factorRefs.roc, label: "ROC 1m",
}]);
assert.equal(adapterSources.factor_candidates[0].source_factors.length, 1);
assert.equal(adapterSources.factor_candidates[0].source_factor_sets.length, 0);
assert.equal(adapterSources.product_group[0].group_ref, "group:day");
const pageCandidateSources = FTTestContentAdapters.chipSources({
  kind: "backtest", manifest: overlayManifest,
  values: {factor_candidates: [
    {ref: factorRefs.roc, alias: "ROC 1m"},
    {ref: factorRefs.value, alias: "Value",
      factor_set_refs: ["factor-set:value"], factor_set_only: true},
  ], factor_source_selections: [
    {ref: factorRefs.roc, alias: "ROC 1m"},
  ], factor_set_selections: [
    {target_ref: "factor-set:value", title_zh: "价值集合"},
  ]},
});
assert.equal(pageCandidateSources.factorCandidateLabel, "2 个");
assert.equal(pageCandidateSources.factor_candidates[0].related_references.length, 2);
assert.match(
  pageCandidateSources.factor_candidates[0].target_ref,
  /^factor-candidates:[0-9a-f]{8}:2$/,
);
assert.equal(pageCandidateSources.factor_candidates[0].source_factors.length, 1);
assert.deepEqual(pageCandidateSources.factor_candidates[0].source_factor_sets, [{
  target_ref: "factor-set:value", label: "价值集合",
}]);
const oneSetCandidateSources = FTTestContentAdapters.chipSources({
  kind: "backtest", manifest: overlayManifest,
  values: {factor_candidates: [
    {ref: factorRefs.value1, alias: "Value 1",
      factor_set_refs: ["factor-set:value"], factor_set_only: true},
    {ref: factorRefs.value2, alias: "Value 2",
      factor_set_refs: ["factor-set:value"], factor_set_only: true},
  ], factor_source_selections: [], factor_set_selections: [
    {target_ref: "factor-set:value", title_zh: "价值集合"},
  ]},
});
assert.equal(oneSetCandidateSources.factorCandidateLabel, "价值集合");
const cacheState = {
  kind: "backtest", manifest: overlayManifest,
  values: {factor_candidates: [
    {ref: factorRefs.first, alias: "First"},
  ], factor_source_selections: [], factor_set_selections: []},
};
assert.equal(
  FTTestContentAdapters.chipSources(cacheState).factorCandidateLabel, "First",
);
cacheState.values.factor_candidates = [
  {ref: factorRefs.second, alias: "Second"},
];
assert.equal(
  FTTestContentAdapters.chipSources(cacheState).factorCandidateLabel, "Second",
  "replacing the candidate array must invalidate its reference index",
);

const persistedStrategySources = FTTestContentAdapters.chipSources({
  kind: "backtest", manifest: overlayManifest,
  values: {factor_candidates: []},
  savedFactors: [{
    ref: factorRefs.history, alias: "SGCCS 历史版本",
  }],
  groups: [{group_ref: "group:night", name: "夜盘"}],
}, {
  factor_candidate_refs: [factorRefs.history],
  product_path_selection_id: "group:night",
});
assert.deepEqual(
  persistedStrategySources.factor,
  [{ref: factorRefs.history, alias: "SGCCS 历史版本"}],
  "a persisted strategy factor must remain a detail target before catalog loading",
);
assert.equal(persistedStrategySources.factorCandidateLabel, "SGCCS 历史版本",
  "a frozen factor ref must resolve through the saved factor descriptor");
assert.equal(
  persistedStrategySources.factor_candidates[0].related_references[0].target_ref,
  factorRefs.history,
);
assert.equal(
  persistedStrategySources.product_path_selection[0],
  "group:night",
  "a persisted product-group reference must still produce the strategy chip",
);
assert.equal(persistedStrategySources.product_group[0].group_ref, "group:night");

const rejectedLegacySources = FTTestContentAdapters.chipSources({
  kind: "backtest", manifest: overlayManifest,
  values: {factor_candidates: [
    {factor_ref: "factor:legacy", factor_alias: "Legacy"},
  ]},
}, {factor_candidate_refs: ["factor:legacy"]});
assert.equal(rejectedLegacySources.factorCandidateLabel, undefined,
  "legacy factor identity fields must not fall back into a chip");
assert.deepEqual(rejectedLegacySources.factor, [],
  "legacy factor identity fields must not resolve a detail target");

const advancedRow = managerList.children.find(item => item.className === "test-settings-manager-row"
  && item.children[1].children[0].children[0].textContent === "高级");
assert.ok(advancedRow, "+ 设置 content should include conditional fields' tab");
const advancedChip = advancedRow.children[1].children[1].children
  .flatMap(group => group.children)
  .find(item => item.className.includes("backend-setting-chip"));
assert.ok(advancedChip, "conditional fields should have a chooser chip");
assert.equal(advancedChip.children[1].textContent, "N/A",
  "a hidden conditional field must be shown as N/A in + 设置");

const describedField = FTTestFieldRow.create(
  "开始日期", new Element("input"), "设置样本开始日期",
);
const describedCopy = describedField.children[0];
assert.equal(describedCopy.children.length, 1,
  "field help must not occupy a permanent explanation row");
const describedHeading = describedCopy.children[0];
assert.equal(describedHeading.className, "test-field-row-heading");
assert.equal(describedHeading.children[1].textContent, "?");
assert.equal(describedHeading.children[1].title, "",
  "field help must not use hover title text");
assert.equal(describedHeading.children[1].attributes["aria-label"], "设置样本开始日期");

const updated = render("SgCCS 5m", () => {});
const updatedGroup = updated.children[1].children[1].children.find(
  item => item.className === "backend-settings-chip-group",
);
const updatedChip = updatedGroup.children.find(item => item.className.includes("backend-setting-chip"));
assert.equal(updatedChip.children[1].textContent, "SgCCS 5m");

const callsBeforeLazyRender = factorPanelCalls;
FTTestSettings.render(manifest, {start_date: "2025-01-02"}, {t: value => value}, {
  activeTab: "factor", mountedTabs: ["factor"],
  lazyState: () => ({status: "idle"}), ensureTab: () => {},
});
assert.equal(factorPanelCalls, callsBeforeLazyRender + 1,
  "an idle tab should render its adapter shell before loading candidates");
console.log("ok");
