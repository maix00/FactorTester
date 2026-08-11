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
assert.deepEqual(inputs.counts(state), {factors: 1, strategies: 1});

inputs.removeFactor(state, "UploadedMomentum");
inputs.removeStrategy(state, "strategies/dynamic_hold.py");
assert.deepEqual(inputs.counts(state), {factors: 0, strategies: 0});
console.log("ok");
