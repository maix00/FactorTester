// The factor-series viewer must be able to show every nested layer of a factor,
// not only the final signal: layer is part of the selection identity.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

global.window = global;
vm.runInThisContext(
  fs.readFileSync('server/manager/web/test-modules/factor-evaluation/results/model.js', 'utf8'),
);
const M = window.FTFactorSeriesModel;

const root = {product: "T.CFE", desc: "T.CFE", values: [], dates: []};
const layer = {product: "T.CFE", layer: "当日差持续期", desc: "当日差持续期", values: [], dates: []};

assert.equal(M.identity(root), "T.CFE", "a plain series keeps the product identity");
assert.equal(M.identity(layer), "T.CFE · 当日差持续期", "a nested layer carries its layer name");
assert.notEqual(M.identity(root), M.identity(layer), "layers must not collapse onto one entry");
assert.equal(M.label(layer), "T.CFE · 当日差持续期", "the option label shows product and layer");

console.log("test_factor_series_nested_layers: ok");
