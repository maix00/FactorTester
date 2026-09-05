"use strict";

const assert = require("assert");
const path = require("path");

global.window = global;
global.document = {
  createElement() {
    return {
      append() {},
      replaceChildren() {},
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
global.FTTestFactorSets = {
  control() { return null; }, selections(state) { return state.values.factor_set_selections || []; },
  setSelections(state, values) { state.values.factor_set_selections = values; },
  async selectSet(_context, state, item) {
    await Promise.resolve();
    state.values.factor_candidates = Array.from({length:8}, (_,i)=>({ref:`member:${i}`,alias:`M${i}`}));
    state.values.factor_set_selections = [item];
  },
};
global.FTTestFactorSelection = {
  candidates(state) { return state.values.factor_candidates || []; },
  factorID(value) { return value?.ref || ""; },
  factorAlias(value) { return value?.alias || ""; },
  syncSelection() {},
};
let renderedCandidateCount = 0;
global.FTTestFactorCandidates = {
  sourceDescription() { return ""; },
  summaryControl(_context,state) { renderedCandidateCount=(state.values.factor_candidates || []).length; return {classList: {add() {}}}; },
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
  factorSetCatalog: {items:[{target_ref:"set:s",title_zh:"Set",member_count:8}],runInputs:new Map()},
  lazy: {factors: {status: "loading", promise: new Promise(resolve => {
    resolveCatalog = resolve;
  })}},
};
const local = FTTestFactorCandidateSources.scopedSourceState(parent, {}, {});
FTTestFactorCandidateSources.panel({t: value => value, session: null}, local, () => {});
assert.deepStrictEqual(pickerOptions.items.map(item => item.label), ["A", "Set"]);

parent.factors = [
  {ref: "factor:a", alias: "A"},
  {ref: "factor:b", alias: "B"},
  {ref: "factor:c", alias: "C"},
];
resolveCatalog();

setImmediate(async () => {
  assert.deepStrictEqual(pickerItems.map(item => item.label), ["A", "B", "C", "Set"]);
  await pickerOptions.onChange(["set:s"]);
  assert.strictEqual(local.values.factor_candidates.length, 8);
  assert.strictEqual(renderedCandidateCount, 8, "mounted summary refreshes after asynchronous set expansion");
  assert.strictEqual(parent.values.factor_candidates.length, 0, "nested selection stays isolated");
  process.stdout.write("ok\n");
});
