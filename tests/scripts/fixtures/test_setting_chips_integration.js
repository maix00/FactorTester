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
for (const path of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
  for (const name of ["FTSettingRules", "FTTestSettingChips", "FTTestSettings"]) {
    if (window[name]) global[name] = window[name];
  }
}

const manifest = {
  tab_lists: {"local-settings": [
    {key: "factor", label: "因子"},
    {key: "time", label: "时间范围"},
  ]},
  defaults: {
    start_date: {
      tab_key: "time", label: "开始日期", chip_template: "开始日期: {value}",
      serialization: {}, options: [],
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
    onChipOpen,
    externalTabs: {factor: () => new Element("factor-panel")},
  });
}

let opened = "";
const first = render("ROC 1m", tabKey => { opened = tabKey; });
assert.deepEqual(first.children.map(item => item.className), [
  "backend-settings-tab-bar",
  "backend-settings-chip-row",
  "backend-settings-host",
]);
const chipRow = first.children[1];
assert.equal(chipRow.children[0].children[1].textContent, "ROC 1m");
chipRow.children[0].listeners.click();
assert.equal(opened, "factor");

const updated = render("SgCCS 5m", () => {});
assert.equal(updated.children[1].children[0].children[1].textContent, "SgCCS 5m");
console.log("ok");
