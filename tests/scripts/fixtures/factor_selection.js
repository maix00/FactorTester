const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/workbench/factor-selection.js", "utf8",
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

const familyState = {
  kind: "backtest", factorRef: "factor:one", factors: [first],
  families: [{family_ref: "family:momentum", family: "Momentum"}],
  values: {factor_candidates: [first], factor_family_ref: "family:momentum"},
  factorCatalog: {selectedFamily: null},
};
assert.equal(selection.selectedFamily(familyState).family, "Momentum");
console.log("ok");
