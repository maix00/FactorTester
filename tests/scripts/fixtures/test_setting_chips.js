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
    {key: "product_path_selection", label: "产品路径"},
    {key: "time", label: "时间范围"},
    {key: "ic_method", label: "IC 类型"},
  ]},
  defaults: {
    factor_owner_ref: {
      tab_key: "factor", label: "因子所有者", chip_template: "因子所有者: {value}",
      serialization: {kind: "factor_owner_selection"}, options: [],
    },
    factor_candidates: {
      tab_key: "factor", label: "因子候选", chip_template: "因子候选: {value}",
      serialization: {kind: "factor_candidate_list"}, options: [],
    },
    product_path_selections: {
      tab_key: "product_path_selection", label: "产品路径选择",
      chip_template: "产品路径选择: {value}",
      serialization: {kind: "product_path_selection_list"}, options: [],
    },
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
  chip_fields: [
    {
      key: "factor_alias", label: "因子", chip_template: "因子: {factorAlias}",
      source_keys: ["factorAlias"], value_resolvers: {}, target_tab: "factor",
    },
    {
      key: "product_path_selection", label: "产品路径",
      chip_template: "产品路径: {productPathSelectionLabel}",
      source_keys: ["product_path_selection"],
      value_resolvers: {productPathSelectionLabel: "product_path_selection_label"},
      target_tab: "product_path_selection",
    },
  ],
};

const descriptors = FTTestSettingChips.descriptors({
  manifest,
  values: {
    factor_owner_ref: "profile:maxa",
    factor_candidates: [{factor_alias: "ROC 1m"}],
    product_path_selections: [{label: "日盘"}, {label: "夜盘"}],
    start_date: "2025-01-02", ic_method: "both", hidden: "secret",
  },
  mountedTabs: ["factor", "product_path_selection", "time", "ic_method"],
  sources: {
    factorAlias: ["ROC 1m", "ROC 3m", "SgCCS 1m", "SgCCS 3m"],
    product_path_selection: [
      {label: "中国期货日盘"}, {label: "中国期货夜盘"}, {label: "能源期货"},
    ],
  },
  context: {t: value => value},
});
assert.deepEqual(descriptors.map(item => [item.label, item.value, item.tabKey]), [
  ["因子", "ROC 1m、ROC 3m +2", "factor"],
  ["产品路径", "中国期货日盘、中国期货夜盘 +1", "product_path_selection"],
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
