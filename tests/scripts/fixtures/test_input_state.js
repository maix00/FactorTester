const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = global.structuredClone
  || (value => JSON.parse(JSON.stringify(value)));
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "test-input-state.js",
});

const state = {};
const inputs = window.FTTestInputState;
inputs.initialize(state);
assert.deepEqual(inputs.requestBody(state), {
  transient_factor_sources: [],
  transient_strategy_sources: [],
  strategy_specs: [],
  strategies: [],
  strategy_bindings: [],
  run_input_dependencies: [],
});

inputs.putFactor(state, {
  factor_id: "UploadedMomentum",
  path: "custom_factors/UploadedMomentum.py",
  source_code: "class UploadedMomentum: pass\n",
}, {
  factor_name: "UploadedMomentum",
  desc: "上传动量",
  params: [{alias: "N", default_value: "2d"}],
  math_expr: "x_t / x_{t-N} - 1",
});
assert.equal(state.transientFactorSources.length, 1);
assert.equal(state.transientFactorFamilies[0].family, "UploadedMomentum");
assert.equal("source_code" in state.transientFactorFamilies[0], false);
assert.equal(state.transientFactorSources[0].source_origin, "upload");
inputs.putFactor(state, {
  factor_id: "UploadedMomentum",
  path: "custom_factors/UploadedMomentum.py",
  source_code: "class UploadedMomentum: pass\n",
  source_origin: "factor_set",
  factor_set_refs: ["factor-set:one"],
}, {factor_name: "UploadedMomentum"});
assert.equal(state.transientFactorSources[0].source_origin, "upload");
inputs.detachFactorSet(state, "factor-set:one");
assert.equal(state.transientFactorSources.length, 1);
assert.throws(() => inputs.putFactor(state, {
  factor_id: "UploadedMomentum",
  path: "custom_factors/UploadedMomentum.py",
  source_code: "class UploadedMomentum: changed\n",
  source_origin: "factor_set",
  factor_set_refs: ["factor-set:two"],
}), /源码冲突/);

inputs.putStrategy(state, {
  path: "strategies/dynamic_hold.py",
  source_code: "class DynamicHold: pass\n",
}, {
  entrypoint: "DynamicHold",
  callbacks: ["on_bar"],
  strategy_spec: {
    strategy_id: "DynamicHold",
    source: "profile:strategies/dynamic_hold.py",
  },
});
const request = inputs.requestBody(state);
assert.equal(request.transient_factor_sources[0].source_code,
  "class UploadedMomentum: pass\n");
assert.equal(request.transient_strategy_sources[0].path,
  "strategies/dynamic_hold.py");
assert.equal(request.strategy_specs[0].strategy_id, "DynamicHold");
assert.deepEqual(inputs.strategyInspection(state, "strategies/dynamic_hold.py"), {
  path: "strategies/dynamic_hold.py",
  entrypoint: "DynamicHold",
  callbacks: ["on_bar"],
  requirements: {},
});
inputs.putDependency(state, {
  path: "strategy-configs/dynamic-hold.yaml",
  content: "target_leverage: 0.4\n",
  content_type: "application/yaml",
  title_zh: "动态持仓参数",
  purpose: "strategy_configuration",
  analyses: ["backtest"],
});
assert.equal(inputs.requestBody(state).run_input_dependencies[0].path,
  "strategy-configs/dynamic-hold.yaml");
assert.deepEqual(inputs.counts(state), {factors: 1, strategies: 1, dependencies: 1});

inputs.removeFactor(state, "UploadedMomentum");
inputs.removeStrategy(state, "strategies/dynamic_hold.py");
assert.equal(inputs.strategyInspection(state, "strategies/dynamic_hold.py"), null);
inputs.removeDependency(state, "strategy-configs/dynamic-hold.yaml");
assert.deepEqual(inputs.counts(state), {factors: 0, strategies: 0, dependencies: 0});

const inlineSource = "class InlineStrategy: pass\n";
inputs.putInlineStrategy(state, {
  temp_ref: "temporary-strategy:one",
  name: "临时策略",
  entrypoint: "InlineStrategy",
  source_code: inlineSource,
  source_sha256: "same-source",
}, {
  binding_id: "strategy-binding:one",
  target_strategy_id: "group-1",
  source: {kind: "inline", temp_ref: "temporary-strategy:one"},
});
inputs.putInlineStrategy(state, {
  temp_ref: "temporary-strategy:two",
  name: "同一源码",
  entrypoint: "InlineStrategy",
  source_code: inlineSource,
  source_sha256: "same-source",
}, {
  binding_id: "strategy-binding:two",
  target_strategy_id: "group-2",
  source: {kind: "inline", temp_ref: "temporary-strategy:two"},
});
assert.equal(state.temporaryStrategies.length, 1,
  "identical inline source must be stored once");
assert.equal(state.strategyBindings.length, 2);
assert.equal(state.strategyBindings[1].source.temp_ref,
  state.strategyBindings[0].source.temp_ref);
inputs.putStrategyBinding(state, {
  binding_id: "strategy-binding:two",
  target_strategy_id: "group-2",
  source: {kind: "library", strategy_ref: "strategy:library", revision_ref: "revision:1"},
});
assert.equal(state.temporaryStrategies.length, 1,
  "an inline source remains while another binding references it");
inputs.removeStrategyBinding(state, "strategy-binding:one");
assert.equal(state.temporaryStrategies.length, 0,
  "unreferenced inline source must be pruned");
state.customStrategyOverrides = {fee_mode: "custom"};
state.customStrategyMountedTabs = ["__strategy__", "factor", "cost"];
const customStrategyRequest = inputs.requestBody(state);
assert.deepEqual(customStrategyRequest.custom_strategy_overrides, {fee_mode: "custom"});
assert.deepEqual(customStrategyRequest.custom_strategy_mounted_tabs,
  ["__strategy__", "factor", "cost"]);
console.log("ok");
