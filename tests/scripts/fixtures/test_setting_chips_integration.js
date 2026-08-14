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
global.FTICHorizonSettings = {normalizeSettingValues: (_manifest, values) => values};
for (const path of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
  for (const name of [
    "FTSettingRules", "FTTestSettingChips", "FTTabChipContent",
    "FTTestContentAdapters", "FTTestSettings",
  ]) {
    if (window[name]) global[name] = window[name];
  }
}

const manifest = {
  settings_sections: [{key: "scope", label: "研究对象", description: "先选对象", order: 10}],
  tab_lists: {"local-settings": [
    {key: "factor", label: "因子", section_key: "scope", content_adapter: "factor_selection"},
    {key: "time", label: "时间范围", section_key: "scope"},
    {key: "advanced", label: "高级", section_key: "scope"},
  ]},
  defaults: {
    start_date: {
      tab_key: "time", label: "开始日期", chip_template: "开始日期: {value}",
      control_template: "date", value: "", serialization: {}, options: [],
    },
    hidden_default: {
      tab_key: "advanced", label: "隐藏条件字段", chip_template: "隐藏条件字段: {value}",
      control_template: "text", value: "default", serialization: {}, options: [],
      visible_when: {mode: ["advanced"]},
    },
  },
  chip_fields: [{
    key: "factor_alias", label: "因子", chip_template: "因子: {factorAlias}",
    source_keys: ["factorAlias"], value_resolvers: {}, target_tab: "factor",
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
  chipSources: {factorAlias: ["ROC 1m"]},
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
    chipSources: {factorAlias: [factorAlias]},
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
factorChip.listeners.click();
assert.equal(opened, "factor");

const host = first.children[2];
assert.equal(host.children[1].children.length, 0,
  "inactive settings tabs should not render their content on first load");
assert.equal(host.children[2].children.length, 0,
  "the settings manager should be lazy until its tab is opened");
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
assert.equal(factorPanelCalls, callsBeforeLazyRender,
  "an idle tab must not execute its adapter code");
console.log("ok");
