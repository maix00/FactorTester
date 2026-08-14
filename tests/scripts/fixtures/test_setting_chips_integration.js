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
  ]},
  defaults: {
    start_date: {
      tab_key: "time", label: "开始日期", chip_template: "开始日期: {value}",
      control_template: "date", value: "", serialization: {}, options: [],
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

let opened = "";
const first = render("ROC 1m", tabKey => { opened = tabKey; });
assert.deepEqual(first.children.map(item => item.className), [
  "test-settings-intro",
  "test-settings-current",
  "test-settings-section",
  "test-settings-section test-settings-manager-section",
]);
assert.equal(first.children[2].children[0].children[0].children[0].textContent, "研究对象");
const chipRow = first.children[1].children[1];
assert.equal(chipRow.children[0].children[1].textContent, "ROC 1m");
chipRow.children[0].listeners.click();
assert.equal(opened, "factor");

const updated = render("SgCCS 5m", () => {});
assert.equal(updated.children[1].children[1].children[0].children[1].textContent, "SgCCS 5m");
console.log("ok");
