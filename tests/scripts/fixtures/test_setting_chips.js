const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.title = "";
    this.type = "";
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}
global.document = {createElement: tagName => new Element(tagName)};
global.FTSettingRules = {
  isVisible: field => field.visible !== false,
  valueFor: (key, field, values) => values[field.serialization?.storage_key || key],
};

eval(fs.readFileSync(process.argv[2], "utf8"));

const manifest = {
  tab_lists: {"local-settings": [
    {key: "factor", label: "因子"},
    {key: "time", label: "时间范围"},
    {key: "ic_method", label: "IC 类型"},
  ]},
  defaults: {
    start_date: {
      tab_key: "time", label: "开始日期", chip_template: "开始日期: {value}",
      serialization: {}, options: [],
    },
    ic_method: {
      tab_key: "ic_method", label: "IC 类型", chip_template: "IC: {value}",
      serialization: {}, options: [
        {value: "both", label: "Rank + Pearson"},
      ],
    },
    hidden: {
      tab_key: "time", label: "隐藏", chip_template: "隐藏: {value}",
      serialization: {}, options: [], visible: false,
    },
  },
  chip_fields: [{
    key: "factor_alias", label: "因子", chip_template: "因子: {factorAlias}",
    source_keys: ["factorAlias"], value_resolvers: {}, target_tab: "factor",
  }],
};

const descriptors = FTTestSettingChips.descriptors({
  manifest,
  values: {start_date: "2025-01-02", ic_method: "both", hidden: "secret"},
  mountedTabs: ["time", "ic_method"],
  sources: {factorAlias: ["ROC 1m", "SgCCS 5m"]},
  context: {t: value => value},
});
assert.deepEqual(descriptors.map(item => [item.label, item.value, item.tabKey]), [
  ["因子", "ROC 1m、SgCCS 5m", "factor"],
  ["开始日期", "2025-01-02", "time"],
  ["IC", "Rank + Pearson", "ic_method"],
]);

let opened = "";
const row = FTTestSettingChips.render({
  manifest,
  values: {start_date: "2025-01-02", ic_method: "both"},
  mountedTabs: ["time", "ic_method"],
  sources: {factorAlias: ["ROC 1m", "SgCCS 5m"]},
  context: {t: value => value},
  onOpen: tabKey => { opened = tabKey; },
});
assert.equal(row.className, "backend-settings-chip-row");
assert.equal(row.children.length, 3);
assert.equal(row.children[0].tagName, "button");
assert.equal(row.children[0].children[0].textContent, "因子");
assert.equal(row.children[0].children[1].textContent, "ROC 1m、SgCCS 5m");
row.children[1].listeners.click();
assert.equal(opened, "time");
console.log("ok");
