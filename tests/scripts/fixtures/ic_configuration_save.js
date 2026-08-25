const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
global.structuredClone = global.structuredClone
  || (value => JSON.parse(JSON.stringify(value)));

function load(path) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
}

function frozenFactor(digest, alias, family) {
  return {
    schema_version: 2, ref: `factor:v2:${digest.repeat(43)}`, alias,
    owner_ref: "profile:maxa",
    identity: {
      family_ref: `factor-family:v2:${digest.toUpperCase().repeat(43)}`,
      family_alias: family,
      family_formula_fingerprint: digest.repeat(64),
      self_formula_fingerprint: digest.repeat(64), params: {},
    },
  };
}
const selectedFactor = frozenFactor("a", "ROC|N:20d|$F:1d", "ROC");
const staleGlobalFactor = frozenFactor("b", "StaleGlobal", "StaleGlobal");
const selectedFactorRef = selectedFactor.ref;
const staleGlobalFactorRef = staleGlobalFactor.ref;
const configurationGroup = {
  config_group_id: "icg-day-roc",
  batch_id: "icb-day-roc",
  name: "日盘 ROC",
  factor_ref: selectedFactorRef,
  product_scope_ref: "product-group:day",
  entry_delay_bars: 1,
  horizon: {sampling: "explicit", bases: ["signal"], multipliers: [1, 5]},
  methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
  editor_mounted_tabs: ["__configuration__", "factor", "product_path_selection"],
};
const persistedProductGroup = {
  group_ref: "product-group:day",
  product_path_selection_id: "product-group:day",
  origin: "catalog",
  // Persisted catalog paths are only authoring hints. They must not become
  // execution authority in the grouped IC writer.
  selected_paths: ["forged/client/path"],
};

global.FTTestFactors = {
  selectedFactor: () => staleGlobalFactor,
  selectedFamily: (_state, factor) => ({
    alias: factor.identity.family_alias,
  }),
};
global.FTTestProducts = {
  groupID: value => value?.group_ref || value?.product_path_selection_id || value?.id || "",
  projection: value => structuredClone(value || {}),
  synchronize: () => {},
};
global.FTICConfigurationGroupModel = {
  selected: state => (state.analysis.configuration_groups || []).filter(item => (
    state.selectedICConfigurationGroupIDs.includes(item.config_group_id)
  )),
};
global.FTTestRunFields = {selection: () => ["ic_series"]};
load("server/manager/web/catalog/factor-model.js");
load("server/manager/web/workbench/setting-rules.js");
load("server/manager/web/workbench/test-configuration-compiler.js");
load("server/manager/web/workbench/ic-configuration.js");
load("server/manager/web/workbench/test-configuration.js");

const manifest = {
  defaults: {
    factor_selections: {execution_policy: "authoring_only", serialization: {}},
    product_path_selection: {execution_policy: "authoring_only", serialization: {}},
    start_date: {serialization: {}},
    ic_lags: {serialization: {}},
    forward_return_horizons: {serialization: {}},
    ic_correlation: {serialization: {}},
    return_price_basis: {serialization: {}},
  },
};
const state = {
  kind: "ic",
  workspace: {
    workspace_id: "workspace-ic",
    configuration: {revision: 7, payload: {}},
  },
  manifest,
  analysis: {configuration_groups: [structuredClone(configurationGroup)]},
  selectedICConfigurationGroupIDs: [configurationGroup.config_group_id],
  factors: [selectedFactor, staleGlobalFactor],
  savedFactors: [],
  groups: [persistedProductGroup],
  values: {
    // The old flat selector intentionally points at another factor. Grouped IC
    // execution must use the configuration group's frozen factor_ref instead.
    factor_selections: [staleGlobalFactor],
    start_date: "2025-01-02",
    ic_lags: [99],
    forward_return_horizons: {sampling: "scale_aware"},
    ic_correlation: "pearson",
    return_price_basis: "stale-global-basis",
  },
};

const executionFactors = FTTestConfiguration.executionFactors(state);
assert.deepEqual(executionFactors.map(item => item.ref), [selectedFactorRef]);

const compiled = FTTestConfiguration.buildAnalysis(
  state,
  executionFactors,
  FTTestFactors.selectedFamily(state, executionFactors[0]),
  configurationGroup,
);
assert.equal(compiled.schema_version, 2);
assert.deepEqual(compiled.configuration_groups, [configurationGroup]);
assert.deepEqual(compiled.product_selections, {
  "product-group:day": {product_path_selection_id: "product-group:day"},
});
assert.deepEqual(compiled.local_settings, {start_date: "2025-01-02"});
assert.equal("factors" in compiled, false);
assert.equal("product_path_selection_id" in compiled, false);
assert.equal("ic_lags" in compiled.local_settings, false);

const missingFactorState = {
  ...state,
  factors: [staleGlobalFactor],
  analysis: {configuration_groups: [structuredClone(configurationGroup)]},
};
assert.throws(
  () => FTTestConfiguration.executionFactors(missingFactorState),
  /factor reference was not found/,
);

(async () => {
  let savedPayload = null;
  const context = {
    t: value => value,
    async api(path, options) {
      assert.equal(path, "/api/workspaces/workspace-ic/configuration");
      savedPayload = JSON.parse(options.body).payload;
      return {configuration: {revision: 8, payload: savedPayload}};
    },
  };
  await FTTestConfiguration.save(context, state, configurationGroup);
  assert.deepEqual(savedPayload.analyses.ic.configuration_groups, [configurationGroup]);
  assert.deepEqual(savedPayload.ui.ic.selected_configuration_group_ids, ["icg-day-roc"]);
  assert.equal(savedPayload.ui.ic.factor_ref, selectedFactorRef);
  assert.deepEqual(savedPayload.ui.ic.product_group_refs, ["product-group:day"]);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
