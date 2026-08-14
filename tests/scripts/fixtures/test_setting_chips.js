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
      show_chip: false, serialization: {kind: "factor_owner_selection"}, options: [],
    },
    factor_candidates: {
      tab_key: "factor", label: "因子候选", chip_template: "因子候选: {value}",
      show_chip: false, serialization: {kind: "factor_candidate_list"}, options: [],
    },
    product_path_selections: {
      tab_key: "product_path_selection", label: "产品路径选择",
      chip_template: "产品路径选择: {value}",
      show_chip: false, serialization: {kind: "product_path_selection_list"}, options: [],
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

const runManifest = {
  run_settings: {key: "run_context"},
  run_fields: [
    {
      key: "task_name", label: "任务名称", default: "", control_template: "text",
      placement: "run_identity", order: 1,
    },
    {
      key: "acting_profile_ref", label: "提交身份", default: "", control_template: "profile",
      placement: "run_identity", order: 2,
    },
    {
      key: "retention_mode", label: "结果保留范围", default: "summary",
      control_template: "select", placement: "run_options", order: 20,
      chip_group: "保留策略", options: [{value: "summary", label: "摘要结果"}],
    },
    {
      key: "output_requests", label: "结果与生成物", default: [],
      control_template: "artifact_output_picker", placement: "outputs", order: 40,
      chip_group: "生成物",
    },
  ],
};
const runDescriptors = FTTestSettingChips.descriptors({
  manifest: runManifest,
  runValues: {task_name: "", acting_profile_ref: "", retention_mode: "summary"},
  outputRequests: [], outputCapabilities: [], profiles: [], context: {t: value => value},
});
assert.deepEqual(runDescriptors.map(item => [item.label, item.value, item.group]), [
  ["任务名称", "未命名（可选）", "运行选项"],
  ["提交身份", "用户本人", "运行选项"],
  ["结果保留范围", "摘要结果", "保留策略"],
  ["结果与生成物", "未选择（使用默认输出）", "生成物"],
]);
const grouped = FTTestSettingChips.render({
  manifest: runManifest,
  runValues: {task_name: "", acting_profile_ref: "", retention_mode: "summary"},
  outputRequests: [], outputCapabilities: [], profiles: [], context: {t: value => value},
});
assert.equal(grouped.children.length, 3);
assert.ok(grouped.children.every(item => item.className === "backend-settings-chip-group"));
assert.equal(grouped.children[0].children[0].textContent, "运行选项");
console.log("ok");
