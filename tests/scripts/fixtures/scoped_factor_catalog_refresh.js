"use strict";

const assert = require("assert");
const path = require("path");

global.window = global;
global.document = {
  createElement() {
    return {
      append() {},
      classList: {add() {}},
      querySelector() { return null; },
    };
  },
};

let pickerOptions;
let pickerItems = [];
global.FTTestObjectPicker = {
  create(_context, options) {
    pickerOptions = options;
    pickerItems = options.items;
    return {
      element: {classList: {add() {}}},
      setItems(items) { pickerItems = items; },
      setValues() {},
    };
  },
  lazyLoading() { return true; },
};
global.FTTestFieldRow = {create(_label, control) { return control; }};
global.FTTestFieldHelp = {forField() { return ""; }};
global.FTTestFactorSets = {control() { return null; }, selections() { return []; }};
global.FTTestFactorSelection = {
  candidates(state) { return state.values.factor_candidates || []; },
  factorID(value) { return value?.ref || ""; },
  factorAlias(value) { return value?.alias || ""; },
  syncSelection() {},
};
global.FTTestFactorCandidates = {
  sourceDescription() { return ""; },
  summaryControl() { return {classList: {add() {}}}; },
};
global.FTSettingRules = {
  storageKey(key) { return key; },
  setValue(_manifest, values, key, _field, value) { values[key] = value; },
};
global.FTFactorModel = {withSourceMetadata(value) { return value; }};

require(path.join(
  __dirname, "../../../server/manager/web/workbench/test-factor-candidate-sources.js",
));

let resolveCatalog;
const parent = {
  manifest: {defaults: {factor_source_selections: {
    serialization: {kind: "factor_source_selection_list"},
  }}},
  values: {factor_candidates: [], factor_source_selections: []},
  factors: [{ref: "factor:a", alias: "A"}],
  savedFactors: [],
  lazy: {factors: {status: "loading", promise: new Promise(resolve => {
    resolveCatalog = resolve;
  })}},
};
const local = FTTestFactorCandidateSources.scopedSourceState(parent, {}, {});
FTTestFactorCandidateSources.panel({t: value => value, session: null}, local, () => {});
assert.deepStrictEqual(pickerOptions.items.map(item => item.label), ["A"]);

parent.factors = [
  {ref: "factor:a", alias: "A"},
  {ref: "factor:b", alias: "B"},
  {ref: "factor:c", alias: "C"},
];
resolveCatalog();

setImmediate(() => {
  assert.deepStrictEqual(pickerItems.map(item => item.label), ["A", "B", "C"]);
  process.stdout.write("ok\n");
});
