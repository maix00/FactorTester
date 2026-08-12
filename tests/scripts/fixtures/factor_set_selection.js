const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const modules = process.argv.slice(2);
global.atob = value => Buffer.from(value, "base64").toString("binary");
global.window = {
  webkit: {messageHandlers: {factorTesterLocalFactorSets: {
    postMessage: async message => {
      assert.equal(message.action, "run-input");
      return {
        descriptor: global.descriptor,
        transient_factor_sources: [{
          factor_id: "Momentum", path: "custom_factors/Momentum.py",
          source_code: "class Momentum: pass\n",
        }],
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

function encode(value) {
  return Buffer.from(value).toString("base64url");
}
const factorRef = [
  "factor", "v1", "profile-maxa", encode("custom_factors/Momentum.py"),
  encode("Momentum|N:20d"), "a".repeat(40), "b".repeat(40),
].join(":");
global.descriptor = {
  target_ref: "factor-set:v1:profile-maxa:path:set:commit:blob",
  manifest: {member_refs: [factorRef]},
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
  const values = await window.FTTestFactorSets.descriptors(context, state, [{
    factor_alias: "Momentum|N:20d",
  }]);
  assert.deepEqual(values, [global.descriptor]);
  assert.equal(state.transientFactorSources.length, 1);
  assert.equal(state.transientFactorSources[0].factor_id, "Momentum");
  assert.equal(state.transientFactorSources[0].source_origin, "factor_set");
  await assert.rejects(
    window.FTTestFactorSets.descriptors(
      context, state, [{factor_alias: "Other|N:20d"}],
    ),
    /成员与当前运行因子不一致/,
  );
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
