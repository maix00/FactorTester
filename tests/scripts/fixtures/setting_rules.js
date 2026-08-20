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
    rules: {default_if: {engine_mode: {basic: "Basic", auto: "Auto", custom: "Custom"}}},
  },
  daily_mark_to_market_enabled: {
    value: false,
    rules: {editable_if: {engine_mode: ["custom"], accounting_mode: ["Custom"]}},
  },
  fixed_margin_ratio: {
    value: 0.1,
    rules: {visible_if: {margin_mode: ["fixed"]}},
  },
  margin_mode: {
    value: "auto",
    rules: {
      default_if: {engine_mode: {basic: "none", auto: "auto", custom: "custom"}},
      disabled_values: {zipline: ["exact"]},
    },
  },
  engine: {value: "native"},
  custom_product_fields: {
    value: [], serialization: {storage_key: "custom_product_fields"},
  },
  fee_custom_product_fields: {
    value: [], serialization: {storage_key: "custom_product_fields"},
  },
  factor_candidates: {value: []},
  factor_role_bindings: {
    value: {}, serialization: {visible_when: {min_items: {factor_candidates: 2}}},
  },
}};

const rules = window.FTSettingRules;
const values = rules.initialValues(manifest, {engine_mode: "basic"});
assert.equal(values.accounting_mode, "Basic");
assert.equal(values.margin_mode, "none");
assert.equal(rules.isEditable(manifest.defaults.daily_mark_to_market_enabled, values), false);
assert.deepEqual(
  rules.lockingFields(manifest.defaults.daily_mark_to_market_enabled, values),
  ["engine_mode", "accounting_mode"],
);
assert.equal(rules.isVisible(manifest.defaults.fixed_margin_ratio, values), false);
assert.equal(
  rules.displayValueFor(
    "daily_mark_to_market_enabled",
    manifest.defaults.daily_mark_to_market_enabled,
    values,
  ),
  false,
  "a locked field should display its declared default",
);

rules.setValue(
  manifest,
  values,
  "daily_mark_to_market_enabled",
  manifest.defaults.daily_mark_to_market_enabled,
  true,
);
assert.equal(
  rules.valueFor("daily_mark_to_market_enabled", manifest.defaults.daily_mark_to_market_enabled, values),
  true,
  "the raw manual value remains in the store for a later editable mode",
);
assert.equal(
  rules.displayValueFor(
    "daily_mark_to_market_enabled",
    manifest.defaults.daily_mark_to_market_enabled,
    values,
  ),
  false,
  "a locked field must not display a stale manual value",
);

rules.setValue(manifest, values, "engine_mode", manifest.defaults.engine_mode, "custom");
assert.equal(values.accounting_mode, "Custom");
assert.equal(values.margin_mode, "custom");
assert.equal(rules.isEditable(manifest.defaults.daily_mark_to_market_enabled, values), true);
rules.setValue(manifest, values, "margin_mode", manifest.defaults.margin_mode, "fixed");
rules.setValue(manifest, values, "engine_mode", manifest.defaults.engine_mode, "auto");
assert.equal(values.margin_mode, "fixed", "a manual field must not be overwritten");
assert.equal(rules.isVisible(manifest.defaults.fixed_margin_ratio, values), true);
assert.equal(
  rules.isVisible(manifest.defaults.factor_role_bindings, values),
  false,
  "factor roles stay hidden until multiple factor candidates exist",
);
values.factor_candidates = [{alias: "A"}, {alias: "B"}];
assert.equal(rules.isVisible(manifest.defaults.factor_role_bindings, values), true);

rules.setValue(manifest, values, "engine", manifest.defaults.engine, "zipline");
assert.deepEqual([...rules.disabledValues(manifest.defaults.margin_mode, values)], ["exact"]);
rules.patchValues(manifest, values, {fee_custom_product_fields: [{product: "SI.GFE"}]});
assert.deepEqual(values.custom_product_fields, [{product: "SI.GFE"}]);

const roles = window.FTTestFactorRoles;
assert.deepEqual(roles.normalize({ranking: {factor_ref: "factor:roc"}, screen: "factor:sgccs"}), {
  ranking: "factor:roc", screen: "factor:sgccs",
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
