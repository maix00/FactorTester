const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "ic-configuration-group-model.js",
});
const model = window.FTICConfigurationGroupModel;

const factorRef = `factor:v2:${"a".repeat(43)}`;
const state = {kind: "ic", analysis: {}};
model.initialize(state);
assert.deepEqual(state.analysis.configuration_groups, []);
assert.deepEqual(state.selectedICConfigurationGroupIDs, []);

const created = model.add(state, {
  name: "日盘 ROC",
  factor_ref: factorRef,
  product_scope_ref: "product-group:pg-day",
  entry_delay_bars: 1,
  horizon: {sampling: "explicit", bases: ["signal"], multipliers: [1, 5]},
  methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
});
assert.match(created.config_group_id, /^icg_/);
assert.match(created.batch_id, /^icb_/);
assert.equal(created.factor_ref, factorRef);
assert.equal(created.product_scope_ref, "product-group:pg-day");
assert.equal(created.entry_delay_bars, 1);
assert.deepEqual(created.editor_mounted_tabs, [
  "__configuration__", "factor", "product_path_selection",
]);
assert.deepEqual(state.selectedICConfigurationGroupIDs, [created.config_group_id]);
assert.throws(() => model.add(state, {
  factor_ref: factorRef,
  product_scope_ref: "product-group:pg-night",
  entry_delay_bars: 0,
  horizon: {sampling: "scale_aware"}, methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
}), /Slice 1.*one configuration group/);

assert.throws(() => model.normalize({
  factor_ref: "not-frozen",
  product_scope_ref: "product-group:pg-day",
  entry_delay_bars: 0,
  horizon: {sampling: "scale_aware"}, methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
}), /frozen factor_ref/);
assert.throws(() => model.normalize({
  factor_ref: `factor:sha256:${"a".repeat(64)}`,
  product_scope_ref: "product-group:pg-day",
  entry_delay_bars: 0,
  horizon: {sampling: "scale_aware"}, methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
}), /frozen factor_ref/);
assert.throws(() => model.normalize({
  factor_ref: factorRef,
  product_scope_ref: "product-group:pg-day",
  entry_delay_bars: [0, 1],
  horizon: {sampling: "scale_aware"}, methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
}), /single non-negative Delay/);

assert.throws(() => model.normalize({
  factor_ref: factorRef,
  product_scope_ref: "product-group:pg-day",
  entry_delay_bars: 0,
  methods: ["rank"],
  return_price_basis: "backtest-close-price",
}), /return_price_basis/);

const updated = model.update(state, created.config_group_id, {entry_delay_bars: 2});
assert.equal(updated.entry_delay_bars, 2);
model.toggle(state, created.config_group_id, false, "single");
assert.deepEqual(state.selectedICConfigurationGroupIDs, []);
model.toggle(state, created.config_group_id, true, "single");
assert.deepEqual(model.selected(state).map(item => item.config_group_id), [created.config_group_id]);

const legacy = {
  kind: "ic",
  analysis: {
    product_path_selection_id: "product-group:legacy",
    factors: [{factor_ref: factorRef}],
    local_settings: {
      ic_lags: [3],
      forward_return_horizons: {sampling: "scale_aware"},
      ic_correlation: "both",
      return_price_basis: "next_close_to_close_adjusted",
    },
  },
};
model.initialize(legacy);
assert.equal(legacy.analysis.configuration_groups.length, 1);
const migrated = legacy.analysis.configuration_groups[0];
assert.equal(migrated.factor_ref, factorRef);
assert.equal(migrated.product_scope_ref, "product-group:legacy");
assert.equal(migrated.entry_delay_bars, 3);
assert.deepEqual(migrated.methods, ["rank", "pearson"]);
assert.equal(migrated.return_price_basis, "next_close_to_close_adjusted");
assert.equal(legacy.analysis.legacy_flat_migrated, true);

const ambiguous = {
  kind: "ic",
  analysis: {
    product_path_selection_id: "product-group:legacy",
    factors: [{factor_ref: factorRef}, {factor_ref: `${factorRef}-two`}],
    local_settings: {ic_lags: [0, 1]},
  },
};
assert.throws(() => model.initialize(ambiguous), /cannot migrate flat IC configuration/);

model.removeSelected(state);
assert.deepEqual(state.analysis.configuration_groups, []);
console.log("ok");
