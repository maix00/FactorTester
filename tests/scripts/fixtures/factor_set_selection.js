const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const modules = process.argv.slice(2);
global.window = {
  webkit: {messageHandlers: {factorTesterLocalFactorSets: {
    postMessage: async message => {
      assert.equal(message.action, "run-input");
      return {
        descriptor: global.descriptor,
        transient_factor_sources: [],
      };
    },
  }}},
};
global.FTSettingRules = {
  storageKey: key => key,
  setValue: (_manifest, values, key, _field, value) => { values[key] = value; },
};
global.FTTestInputState = {
  putFactor: (state, source) => { state.transientFactorSources.push(source); },
  detachFactorSet: (state, targetRef) => {
    state.transientFactorSources = state.transientFactorSources.filter(source => (
      !(source.factor_set_refs || []).includes(targetRef)
    ));
  },
};
for (const module of modules) {
  vm.runInThisContext(fs.readFileSync(module, "utf8"), {filename: module});
}
global.FTFactorModel = window.FTFactorModel;
global.FTTestFactorSelection = window.FTTestFactorSelection;

const member = {
  schema_version: 2,
  ref: `factor:v2:${"A".repeat(43)}`,
  alias: "Momentum|N:20d",
  owner_ref: "profile:maxa",
  identity: {
    family_ref: `factor-family:v2:${"B".repeat(43)}`,
    family_alias: "Momentum",
    family_formula_fingerprint: "a".repeat(64),
    self_formula_fingerprint: "b".repeat(64),
    params: {N: "20d"},
  },
};
global.descriptor = {
  target_ref: `factor-set:v2:${"C".repeat(43)}`,
  manifest: {
    schema_version: 2,
    ref: `factor-set:v2:${"C".repeat(43)}`,
    alias: "Momentum set",
    owner_ref: "profile:maxa",
    identity: {
      set_id: "momentum",
      member_fingerprint: "d".repeat(64),
      members: [member],
    },
  },
};
const state = {
  kind: "ic",
  manifest: {defaults: {factor_set_selections: {
    serialization: {kind: "factor_set_selection_list", native_run_input_action: "run-input"},
  }}},
  values: {factor_set_selections: [{
    target_ref: global.descriptor.target_ref, visibility: "local",
  }]},
  factorSetCatalog: {runInputs: new Map()},
  transientFactorSources: [],
};

(async () => {
  const context = {t: value => value};
  const values = await window.FTTestFactorSets.descriptors(context, state, [member]);
  assert.deepEqual(values, [global.descriptor]);
  assert.equal(state.transientFactorSources.length, 0);
  await assert.rejects(
    window.FTTestFactorSets.descriptors(
      context, state, [{...member, ref: `factor:v2:${"D".repeat(43)}`, alias: "Other|N:20d"}],
    ),
    /成员与当前运行因子不一致/,
  );
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
