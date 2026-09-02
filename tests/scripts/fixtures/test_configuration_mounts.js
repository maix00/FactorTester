const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
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
const factor = frozenFactor("a", "ROC", "MmRateOfChg");
const nestedTemporaryFactor = {
  ...frozenFactor("c", "InlineThreshold", "InlineThreshold"),
  temporary: true, source_kind: "transient",
  source_code: "class InlineThreshold: pass\n",
};
const secondFactor = frozenFactor("b", "Momentum", "Momentum");
const configurationGroup = {
  config_group_id: "icg-day-roc",
  batch_id: "icb-day-roc",
  name: "日盘 ROC",
  factor_ref: factor.ref,
  product_scope_ref: "product-group:persisted",
  entry_delay_bars: 0,
  horizon: {sampling: "scale_aware"},
  methods: ["rank"],
  return_price_basis: "next_open_to_open_adjusted",
  editor_mounted_tabs: ["__configuration__", "factor", "product_path_selection"],
};
global.FTTestFactors = {
  selectedFactor: state => state.noOuterFactor ? null : factor,
  selectedFamily: () => ({alias: "MmRateOfChg", ref: factor.identity.family_ref}),
};
global.FTTestProducts = {
  synchronize() {}, groupID: group => group.group_ref || group.id,
  projection: group => ({
    product_path_selection_id: group.group_ref || group.id,
    product_group_template_id: group.group_ref || group.id,
    label: group.name || group.group_ref || group.id,
    selected_paths: group.paths,
    paths: group.paths,
  }),
  selectedProjections: () => [{product_path_selection_id: "day", selected_paths: ["CNFutures"]}],
};
global.FTTestConfigurationCompiler = {
  authoringSettings: (_manifest, values) => structuredClone(values),
  executionSettings: (_manifest, values) => structuredClone(values),
  sanitizeExecutionPayload: (_manifest, payload) => structuredClone(payload),
  factorSubjects: factors => (factors || []).map(item => ({
    schema_version: item.schema_version,
    ref: item.ref,
    alias: item.alias,
    owner_ref: item.owner_ref,
    identity: structuredClone(item.identity),
  })),
};
global.FTTestRunFields = {selection: () => [{name: "ic_statistics_data"}]};
global.FTTestState = {
  registeredRunValues: () => ({}),
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/catalog/factor-model.js", "utf8",
), {filename: "factor-model.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/ic-configuration.js", "utf8",
), {filename: "ic-configuration.js"});
global.FTICConfiguration = window.FTICConfiguration;
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {filename: process.argv[2]});

const requests = [];
const state = {
  kind: "ic", manifest: {
    defaults: {}, research_configuration_schema_version: 3,
  }, values: {
    factor_candidates: [{
      ...factor, temporary: true, source_origin: "test_inline",
      factor_dependencies: [nestedTemporaryFactor, nestedTemporaryFactor],
    }, secondFactor],
    factor_selections: [factor],
    category_candidates: [{
      id: "inline-category:session", temporary: true, title_zh: "会话分类",
    }],
  },
  factors: [factor, secondFactor], families: [], groups: [{
    id: "inline-product-group:session", temporary: true,
    paths: ["CNFutures/**"],
  }, {
    group_ref: "product-group:persisted", name: "持久产品组",
    paths: ["CNFutures/day/**"],
  }], analysis: {configuration_groups: [configurationGroup]},
  selectedICConfigurationGroupIDs: [configurationGroup.config_group_id],
  settingsMountedTabs: ["factor", "delay"],
  factorRef: factor.ref, groupRef: "day", groupRefs: ["day"],
  outputCapabilities: [], outputRequests: [],
  transientFactorSources: [{
    factor_id: "InlineFactor", path: "inline/InlineFactor.py",
    source_code: "class InlineFactor: pass\n",
  }],
  factorSetCatalog: {items: [{
    target_ref: "factor-set:v1:temporary", temporary: true,
    manifest: {identity: {members: []}},
  }]},
  workspace: {workspace_id: "workspace-1", configuration: {
    configuration_id: "configuration-1", revision: 1, payload: {},
  }},
};

const equivalentVisibleFactor = structuredClone(factor);
equivalentVisibleFactor.alias = "同公式的目录别名";
equivalentVisibleFactor.owner_ref = "profile:subordinate";
state.factors.unshift(equivalentVisibleFactor);
assert.equal(
  window.FTTestConfiguration.executionFactors(state)[0].owner_ref,
  factor.owner_ref,
  "formula-identical catalog records use the selected candidate provenance",
);
const conflictingFactor = structuredClone(equivalentVisibleFactor);
conflictingFactor.identity.self_formula_fingerprint = "f".repeat(64);
assert.throws(
  () => window.FTTestConfiguration.executionFactors({
    ...state,
    factors: [conflictingFactor],
  }),
  /factor ref is bound to conflicting records/,
  "a genuine executable-formula conflict remains rejected",
);

assert.deepEqual(
  window.FTTestConfiguration.executionFactors({
    ...state,
    values: {...state.values, factor_selections: []},
  }).map(item => item.ref),
  [factor.ref],
  "grouped IC execution must use the group's frozen factor, not the legacy global selection",
);
const context = {t: value => value, api: async (path, options) => {
  requests.push({path, body: JSON.parse(options.body)});
  return {configuration: {
    configuration_id: `configuration-${requests.length}`,
    revision: 2,
    payload: JSON.parse(options.body).payload,
  }};
}};

(async () => {
  await window.FTTestConfiguration.save(context, state, configurationGroup);
  assert.deepEqual(
    requests[0].body.payload.ui.ic.mounted_tabs,
    ["factor", "delay"],
  );
  const temporary = requests[0].body.payload.shared.temporary_objects;
  assert.deepEqual(
    requests[0].body.payload.shared.factors.map(item => item.ref),
    [factor.ref],
    "workspace subjects must contain only the registered IC factor selection",
  );
  const icAnalysis = requests[0].body.payload.analyses.ic;
  assert.deepEqual(Object.keys(icAnalysis).sort(), [
    "configuration_groups", "execution", "product_selections", "schema_version",
  ], "IC authoring must persist the grouped typed shape");
  assert.deepEqual(icAnalysis.configuration_groups, [configurationGroup]);
  assert.deepEqual(icAnalysis.product_selections, {
    "product-group:persisted": {
      product_path_selection_id: "product-group:persisted",
    },
  }, "persistent groups must write only their stable reference");
  assert.equal(icAnalysis.product_path_selection, undefined);
  assert.equal(icAnalysis.paths, undefined);
  assert.equal(icAnalysis.settings, undefined);
  assert.deepEqual(
    requests[0].body.payload.ui.ic.settings.factor_selections.map(item => item.ref),
    [factor.ref],
    "authoring settings must persist the registered selection field",
  );
  assert.deepEqual(temporary.factors.map(item => item.ref), [
    nestedTemporaryFactor.ref, factor.ref,
  ]);
  assert.equal(temporary.factors[0].source_code, "class InlineThreshold: pass\n");
  assert.equal(temporary.factor_sets[0].target_ref, "factor-set:v1:temporary");
  assert.equal(temporary.product_groups[0].id, "inline-product-group:session");
  assert.equal(temporary.categories[0].id, "inline-category:session");
  assert.equal(temporary.factor_sources[0].factor_id, "InlineFactor");

  const backtestState = {
    ...state,
    kind: "backtest",
    analysis: {
      groups: [{
        id: "strategy-1",
        factor_candidate_refs: [factor.ref],
        product_path_selection_id: "product-group:persisted",
        product_path_selection: {
          product_path_selection_id: "product-group:persisted",
          selected_paths: [],
        },
      }],
      ls_configs: [],
    },
    workspace: {
      workspace_id: "workspace-2",
      configuration: {
        configuration_id: "configuration-2", revision: 1, payload: {},
      },
    },
    groupRef: "",
    groupRefs: [],
    noOuterFactor: true,
  };
  await window.FTTestConfiguration.save(
    context, backtestState, {id: "__backtest__", label: "回测任务"},
  );
  const backtestPayload = requests[1].body.payload;
  assert.equal(backtestPayload.ui.backtest.product_group_ref, undefined,
    "backtest must not persist a global product-group execution scope");
  assert.deepEqual(
    backtestPayload.analyses.backtest.groups[0].product_path_selection,
    {
      product_path_selection_id: "product-group:persisted",
      product_group_template_id: "product-group:persisted",
      label: "持久产品组",
      selected_paths: ["CNFutures/day/**"],
      paths: ["CNFutures/day/**"],
    },
  );
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
