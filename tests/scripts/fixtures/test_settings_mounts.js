const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = value => JSON.parse(JSON.stringify(value));
global.FTICHorizonSettings = {normalizeSettingValues: (_manifest, values) => values};
for (const path of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
  if (window.FTSettingRules) global.FTSettingRules = window.FTSettingRules;
}

const manifest = {
  tab_lists: {"local-settings": [
    {key: "test_template", label: "测试模板"},
    {key: "engine", label: "执行引擎"},
    {key: "factor", label: "因子"},
    {key: "product_path_selection", label: "产品组"},
    {key: "category", label: "分类"},
    {key: "fee", label: "费率"},
    {key: "margin", label: "保证金"},
  ]},
  default_mounted_tabs: {"local-settings": ["test_template", "engine"]},
  defaults: {
    setting_template: {
      tab_key: "test_template", value: null,
      serialization: {kind: "setting_template"},
    },
    engine: {tab_key: "engine", value: "native", serialization: {}},
    factors: {
      tab_key: "factor", value: [],
      serialization: {kind: "factor_selection_list"},
    },
    products: {
      tab_key: "product_path_selection", value: [],
      serialization: {kind: "product_path_selection_list"},
    },
    category: {
      tab_key: "category", value: "", serialization: {kind: "category_selection"},
    },
    fee_rate: {tab_key: "fee", value: 0.001, serialization: {}},
    fee_products: {
      tab_key: "fee", value: [],
      serialization: {
        kind: "custom_product_overrides", storage_key: "custom_product_fields",
        module_filter: "fee", fields: [{value: "open_fee", module: "fee"}],
      },
    },
    margin_products: {
      tab_key: "margin", value: [],
      serialization: {
        kind: "custom_product_overrides", storage_key: "custom_product_fields",
        module_filter: "margin", fields: [{value: "margin_rate", module: "margin"}],
      },
    },
  },
};

assert.deepEqual(
  window.FTTestSettings.initialMountedTabs(manifest),
  ["engine", "factor", "product_path_selection"],
);
assert.deepEqual(window.FTTestSettings.initialMountedTabs(manifest, ["category"]), ["category"]);

const values = window.FTSettingRules.initialValues(manifest, {
  fee_rate: 0.01,
  custom_product_fields: [
    {product: "SI.GFE", field: "open_fee", value: 2},
    {product: "SI.GFE", field: "margin_rate", value: 0.12},
  ],
});
window.FTTestSettings.resetTabValues(manifest, values, "fee");
assert.equal(values.fee_rate, 0.001);
assert.deepEqual(values.custom_product_fields, [
  {product: "SI.GFE", field: "margin_rate", value: 0.12},
]);
console.log("ok");
