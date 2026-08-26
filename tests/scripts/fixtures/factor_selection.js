const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/factor-selection.js", "utf8",
), {filename: "factor-selection.js"});

const selection = window.FTTestFactorSelection;
function factor(digest, alias, family) {
  return {
    schema_version: 2,
    ref: `factor:v2:${digest.repeat(43)}`,
    alias,
    owner_ref: "user:alice",
    identity: {
      family_ref: `factor-family:v2:${family[0].repeat(43)}`,
      family_alias: family,
      family_formula_fingerprint: digest.repeat(64),
      self_formula_fingerprint: digest.repeat(64),
      params: {},
    },
  };
}
const first = factor("A", "One", "Momentum");
const second = factor("B", "Two", "Value");
const state = {
  kind: "ic", factorRef: "", factors: [], families: [],
  values: {factor_candidates: [], factor_selections: []},
};
selection.addCandidate(state, first);
selection.addCandidate(state, second);
assert.deepEqual(selection.selectedIDs(state), [first.ref, second.ref]);
assert.equal(selection.selectedFactor(state).alias, "Two");
selection.setSelected(state, first, false);
assert.deepEqual(selection.selectedIDs(state), [second.ref]);
selection.removeCandidate(state, second);
assert.deepEqual(selection.candidates(state), [first]);

selection.addCandidate(state, {
  ...first, factor_set_refs: ["factor-set:one"], factor_set_only: true,
});
selection.detachFactorSet(state, "factor-set:one");
assert.equal(selection.candidates(state).length, 1,
  "a directly selected candidate must survive set removal");
const setOnly = {
  ...factor("C", "SetOnly", "Momentum"),
  factor_set_refs: ["factor-set:one"], factor_set_only: true,
};
selection.addCandidate(state, setOnly);
selection.detachFactorSet(state, "factor-set:one");
assert.equal(selection.candidates(state).some(item => item.ref === setOnly.ref), false);

const familyState = {
  kind: "backtest", factorRef: first.ref, factors: [first],
  families: [{ref: first.identity.family_ref, alias: "Momentum"}],
  values: {factor_candidates: [first], factor_family_ref: first.identity.family_ref},
  factorCatalog: {selectedFamily: null},
};
assert.equal(selection.selectedFamily(familyState).alias, "Momentum");
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

// The factor editor returns a canonical v2 record after saving a parameter
// row.  This is the exact shape that used to be lost by normalizeSaved().
const inlineSaved = {
  schema_version: 2,
  ref: "factor:v2:" + "C".repeat(43),
  alias: "InlineMomentum|N:5d",
  owner_ref: "user:alice",
  identity: {
    family_ref: "factor-family:v2:" + "D".repeat(43),
    family_alias: "InlineMomentum",
    family_formula_fingerprint: "e".repeat(64),
    self_formula_fingerprint: "f".repeat(64),
    params: {N: "5d"},
  },
};
const savedState = {
  kind: "backtest", factorRef: "", factors: [],
  values: {factor_candidates: [], factor: ""},
};
selection.addCandidate(savedState, inlineSaved);
assert.equal(selection.candidates(savedState)[0].alias, "InlineMomentum|N:5d");
assert.equal(savedState.values.factor, "InlineMomentum|N:5d");
console.log("ok");
