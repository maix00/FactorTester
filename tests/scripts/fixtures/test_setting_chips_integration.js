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
    this.classList = {toggle() {}};
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

global.document = {createElement: tagName => new Element(tagName)};
global.FTTestFactors = {panel: () => new Element("factor-panel")};
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

function render(factorAlias, onChipOpen) {
  return FTTestSettings.render(manifest, {start_date: "2025-01-02"}, {
    t: value => value,
  }, {
    activeTab: "factor",
    mountedTabs: ["factor", "time"],
    chipSources: {factorAlias: [factorAlias]},
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
assert.deepEqual(first.children.map(item => item.className), [
  "test-settings-intro",
  "backend-settings-tab-bar",
  "test-settings-current",
  "backend-settings-host",
]);
assert.ok(first.children[1].children.every(button => button.children.length === 1),
  "test setting tabs should render only their title");
assert.equal(first.children[1].children[0].children[0].textContent, "因子");
const chipRow = first.children[2].children[1];
assert.equal(chipRow.children[0].children[1].textContent, "ROC 1m");
chipRow.children[0].listeners.click();
assert.equal(opened, "factor");

const host = first.children[3];
const managePanel = host.children[host.children.length - 1];
const manager = managePanel.children[0];
const managerList = manager.children[1];
const timeRow = managerList.children.find(item => item.className === "test-settings-manager-row"
  && item.children[1].children[0].children[0].textContent === "时间范围");
assert.ok(timeRow, "+ 设置 content should list every tab");
assert.ok(timeRow.children[1].children[1].children.length >= 1,
  "+ 设置 content should show default chips");
assert.equal(timeRow.children[1].children[1].children[0].children[1].textContent, "未设置（默认）");

const updated = render("SgCCS 5m", () => {});
assert.equal(updated.children[2].children[1].children[0].children[1].textContent, "SgCCS 5m");
console.log("ok");
