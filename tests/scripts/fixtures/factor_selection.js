const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/factor-selection.js", "utf8",
), {filename: "factor-selection.js"});

const selection = window.FTTestFactorSelection;
const first = {factor_ref: "factor:one", factor_alias: "One", family: "Momentum"};
const second = {factor_ref: "factor:two", factor_alias: "Two", family: "Value"};
const state = {
  kind: "ic", factorRef: "", factors: [], families: [],
  values: {factor_candidates: [], factor_selections: []},
};
selection.addCandidate(state, first);
selection.addCandidate(state, second);
assert.deepEqual(selection.selectedIDs(state), ["factor:one", "factor:two"]);
assert.equal(selection.selectedFactor(state).factor_ref, "factor:two");
selection.setSelected(state, first, false);
assert.deepEqual(selection.selectedIDs(state), ["factor:two"]);
selection.removeCandidate(state, second);
assert.deepEqual(selection.candidates(state), [first]);

selection.addCandidate(state, {
  ...first, factor_set_refs: ["factor-set:one"], factor_set_only: true,
});
selection.detachFactorSet(state, "factor-set:one");
assert.equal(selection.candidates(state).length, 1,
  "a directly selected candidate must survive set removal");
const setOnly = {
  factor_ref: "factor:set-only", factor_alias: "SetOnly",
  factor_set_refs: ["factor-set:one"], factor_set_only: true,
};
selection.addCandidate(state, setOnly);
selection.detachFactorSet(state, "factor-set:one");
assert.equal(selection.candidates(state).some(item => item.factor_ref === "factor:set-only"), false);

const familyState = {
  kind: "backtest", factorRef: "factor:one", factors: [first],
  families: [{family_ref: "family:momentum", family: "Momentum"}],
  values: {factor_candidates: [first], factor_family_ref: "family:momentum"},
  factorCatalog: {selectedFamily: null},
};
assert.equal(selection.selectedFamily(familyState).family, "Momentum");
const backtestState = {
  kind: "backtest", factorRef: "", factors: [],
  values: {factor_candidates: [], factor: ""},
};
selection.addCandidate(backtestState, first, {select: false});
selection.addCandidate(backtestState, second, {select: false});
assert.equal(backtestState.values.factor, "One",
  "outer backtest primary factor is selected automatically from the pool");
selection.removeCandidate(backtestState, first);
assert.equal(backtestState.values.factor, "Two");
console.log("ok");
