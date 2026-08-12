const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/setting-rules.js", "utf8",
), {filename: "setting-rules.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/factor-roles.js", "utf8",
), {filename: "factor-roles.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/custom-product-overrides.js", "utf8",
), {filename: "custom-product-overrides.js"});

const manifest = {defaults: {
  engine_mode: {value: "auto"},
  accounting_mode: {
    value: "Auto",
    default_when: {engine_mode: {basic: "Basic", auto: "Auto", custom: "Custom"}},
  },
  daily_mark_to_market_enabled: {
    value: false,
    editable_when: {engine_mode: ["custom"], accounting_mode: ["Custom"]},
  },
  fixed_margin_ratio: {
    value: 0.1,
    visible_when: {margin_mode: ["fixed"]},
  },
  margin_mode: {
    value: "auto",
    default_when: {engine_mode: {basic: "none", auto: "auto", custom: "custom"}},
    disabled_values_by_engine: {zipline: ["exact"]},
  },
  engine: {value: "native"},
  custom_product_fields: {
    value: [], serialization: {storage_key: "custom_product_fields"},
  },
  fee_custom_product_fields: {
    value: [], serialization: {storage_key: "custom_product_fields"},
  },
}};

const rules = window.FTSettingRules;
const values = rules.initialValues(manifest, {engine_mode: "basic"});
assert.equal(values.accounting_mode, "Basic");
assert.equal(values.margin_mode, "none");
assert.equal(rules.isEditable(manifest.defaults.daily_mark_to_market_enabled, values), false);
assert.equal(rules.isVisible(manifest.defaults.fixed_margin_ratio, values), false);

rules.setValue(manifest, values, "engine_mode", manifest.defaults.engine_mode, "custom");
assert.equal(values.accounting_mode, "Custom");
assert.equal(values.margin_mode, "custom");
assert.equal(rules.isEditable(manifest.defaults.daily_mark_to_market_enabled, values), true);
rules.setValue(manifest, values, "margin_mode", manifest.defaults.margin_mode, "fixed");
rules.setValue(manifest, values, "engine_mode", manifest.defaults.engine_mode, "auto");
assert.equal(values.margin_mode, "fixed", "a manual field must not be overwritten");
assert.equal(rules.isVisible(manifest.defaults.fixed_margin_ratio, values), true);

rules.setValue(manifest, values, "engine", manifest.defaults.engine, "zipline");
assert.deepEqual([...rules.disabledValues(manifest.defaults.margin_mode, values)], ["exact"]);
rules.patchValues(manifest, values, {fee_custom_product_fields: [{product: "SI.GFE"}]});
assert.deepEqual(values.custom_product_fields, [{product: "SI.GFE"}]);

const roles = window.FTTestFactorRoles;
assert.deepEqual(roles.normalize({ranking: {factor_alias: "ROC"}, screen: "SgCCS"}), {
  ranking: "ROC", screen: "SgCCS",
});
assert.deepEqual(roles.visibleRoles({serialization: {
  roles_by_strategy_kind: {group: ["ranking", "screen"], threshold: ["entry", "exit"]},
}}, {strategy_intent_mode: "threshold"}), ["entry", "exit"]);

const overrides = window.FTCustomProductOverrides;
const editor = {serialization: {
  module_filter: "fee",
  fields: [
    {value: "OpenRatioByMoney", module: "fee"},
    {value: "LongMarginRatioByMoney", module: "margin"},
  ],
}};
const allRows = [
  {product: "SI.GFE", field: "OpenRatioByMoney", value: 0.001},
  {product: "SI.GFE", field: "LongMarginRatioByMoney", value: 0.12},
];
assert.deepEqual(overrides.scopedRows(editor, allRows), [allRows[0]]);
assert.deepEqual(
  overrides.replaceScopedRows(editor, allRows, [
    {product: "UR.CZC", field: "OpenRatioByMoney", value: 0.002},
  ]),
  [allRows[1], {product: "UR.CZC", field: "OpenRatioByMoney", value: 0.002}],
);

console.log("ok");
