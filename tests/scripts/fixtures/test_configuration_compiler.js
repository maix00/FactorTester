const assert = require("assert").strict;
const fs = require("fs");

global.window = globalThis;
global.structuredClone = global.structuredClone || (value => JSON.parse(JSON.stringify(value)));

const source = process.argv[2];
const configurationSource = process.argv[3];
eval(fs.readFileSync(
  "server/manager/web/workbench/setting-rules.js", "utf8",
));
eval(fs.readFileSync(source, "utf8"));
eval(fs.readFileSync(
  "server/manager/web/workbench/ic-configuration.js", "utf8",
));
if (configurationSource) {
  global.FTTestProducts = {
    groupID: group => group.group_ref || group.product_group_ref || group.id
      || group.product_group_template_id || group.product_path_selection_id,
    projection: group => group.product_path_selection,
  };
  global.FTTestFactors = {};
  eval(fs.readFileSync(configurationSource, "utf8"));
}

const manifest = {
  defaults: {
    factor_owner_ref: {execution_policy: "authoring_only", serialization: {kind: "factor_owner_selection"}},
    factor_git_commit: {execution_policy: "authoring_only", serialization: {kind: "factor_revision_selection"}},
    factor_family_ref: {execution_policy: "authoring_only", serialization: {kind: "factor_family_selection"}},
    factor_params: {execution_policy: "authoring_only", serialization: {kind: "factor_parameter_values"}},
    factor_candidates: {execution_policy: "authoring_only", serialization: {kind: "factor_candidate_list"}},
    factor_selections: {execution_policy: "authoring_only", serialization: {kind: "factor_selection_list"}},
    product_path_candidates: {execution_policy: "authoring_only", serialization: {kind: "product_path_candidate_list"}},
    product_path_selections: {execution_policy: "authoring_only", serialization: {kind: "product_path_selection_list"}},
    category_candidates: {execution_policy: "authoring_only", serialization: {kind: "category_candidate_list"}},
    category: {serialization: {kind: "category_selection"}},
    setting_template: {execution_policy: "authoring_only", serialization: {kind: "setting_template"}},
    custom_fee_editor: {
      serialization: {kind: "custom_product_overrides", storage_key: "custom_product_fields"},
    },
    start_date: {serialization: {}},
    ic_decay_lags: {serialization: {}},
    forward_return_horizons: {serialization: {}},
    ic_lags: {serialization: {}},
    split_count: {scope_policy: "group_only", serialization: {}},
  },
};
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
const factor = frozenFactor("a", "ROC|N:20d|$F:1d", "ROC");
const product = {product_path_selection_id: "day", selected_paths: ["CNFutures/day"]};
const values = {
  factor_owner_ref: "profile:maxa",
  factor_git_commit: "a".repeat(40),
  factor_family_ref: "factor-family:v1:roc",
  factor_params: {N: "20d"},
  factor_candidates: [factor],
  factor_selections: [factor],
  product_path_candidates: [product],
  product_path_selections: [product],
  category_candidates: [{id: "industry"}],
  category: "industry",
  setting_template: "template-1",
  custom_product_fields: [{product: "SI.GFE", field: "margin", value: 0.12}],
  start_date: "2025-01-02",
  ic_decay_lags: [1, 5],
  forward_return_horizons: {
    sampling: "explicit", bases: ["signal", "1m"], multipliers: [1, 5],
  },
  ic_lags: [0, 1],
  split_count: 5,
  stale_unknown_field: "must-not-enter-execution",
};

const authoring = FTTestConfigurationCompiler.authoringSettings(manifest, values);
const execution = FTTestConfigurationCompiler.executionSettings(manifest, values);

assert.deepEqual(authoring, values);
assert.deepEqual(execution, {
  category: "industry",
  custom_product_fields: [{product: "SI.GFE", field: "margin", value: 0.12}],
  start_date: "2025-01-02",
  ic_decay_lags: [1, 5],
  forward_return_horizons: {
    sampling: "explicit", bases: ["signal", "1m"], multipliers: [1, 5],
  },
  ic_lags: [0, 1],
});
assert.equal("factor_candidates" in execution, false);
assert.equal("factor_selections" in execution, false);
assert.equal("product_path_selections" in execution, false);
assert.equal("split_count" in execution, false);
assert.equal("stale_unknown_field" in execution, false);

const scopedPayload = FTTestConfigurationCompiler.sanitizeExecutionPayload(
  manifest,
  {
    category: "industry",
    start_date: "2025-01-02",
    split_count: 5,
    settings: {split_count: 5},
    local_settings: {
      category: "industry", start_date: "2025-01-02", split_count: 5,
    },
    groups: [{id: "group-1", split_count: 5}],
  },
  values,
  {stripRootRegistered: true},
);
assert.equal("split_count" in scopedPayload, false);
assert.equal("category" in scopedPayload, false);
assert.equal("start_date" in scopedPayload, false);
assert.equal(scopedPayload.settings, undefined);
assert.equal(scopedPayload.local_settings, undefined);
assert.equal(scopedPayload.groups[0].split_count, 5);

if (configurationSource) {
  const backtestState = {
    kind: "backtest",
    manifest,
    values,
    factors: [factor],
    savedFactors: [factor],
    groups: [{
      product_path_selection_id: "day",
      selected_paths: ["CNFutures/day"],
    }],
    analysis: {
      ...values,
      groups: [{
        id: "group-1", factor_candidate_refs: [factor.ref],
        split_count: 5,
        product_path_selection: {
          group_ref: "day",
          selected_paths: ["CNFutures/day"],
        },
      }],
    },
  };
  const compiledBacktest = FTTestConfiguration.buildAnalysis(
    backtestState, [factor], factor, backtestState.analysis.groups[0],
  );
  for (const key of Object.keys(manifest.defaults)) {
    assert.equal(
      key in compiledBacktest, false,
      `backtest RunSpec must not retain registered root field: ${key}`,
    );
  }
  assert.equal(compiledBacktest.execution.settings.category, "industry");
  assert.equal(compiledBacktest.execution.settings.start_date, "2025-01-02");
  assert.equal(compiledBacktest.groups[0].split_count, 5);
  assert.equal(compiledBacktest.groups[0].product_path_selection_id, "day");
  assert.equal(
    compiledBacktest.groups[0].product_path_selection.product_path_selection_id,
    "day",
  );
}

const conditionalManifest = {
  defaults: {
    mode: {value: "basic", serialization: {}},
    conditional_execution: {
      value: "default",
      serialization: {},
      rules: {visible_if: {mode: ["advanced"]}},
    },
    conditional_authoring: {
      value: "default",
      execution_policy: "authoring_only",
      serialization: {},
      rules: {visible_if: {mode: ["advanced"]}},
    },
    locked_execution: {
      value: "declared",
      serialization: {},
      rules: {
        editable_if: {mode: ["advanced"]},
        default_if: {mode: {basic: "automatic"}},
      },
    },
  },
};
const basicValues = {
  mode: "basic",
  conditional_execution: "stale-execution",
  conditional_authoring: "stale-authoring",
  locked_execution: "stale-locked",
};
assert.deepEqual(
  FTTestConfigurationCompiler.authoringSettings(conditionalManifest, basicValues),
  {mode: "basic", locked_execution: "automatic"},
);
assert.deepEqual(
  FTTestConfigurationCompiler.executionSettings(conditionalManifest, basicValues),
  {mode: "basic", locked_execution: "automatic"},
);
const advancedValues = {...basicValues, mode: "advanced", conditional_execution: "enabled",
  conditional_authoring: "enabled", locked_execution: "manual"};
assert.deepEqual(
  FTTestConfigurationCompiler.executionSettings(conditionalManifest, advancedValues),
  {mode: "advanced", conditional_execution: "enabled", locked_execution: "manual"},
);

const stalePayload = {
  mode: "basic",
  conditional_execution: "old-root-value",
  conditional_authoring: "old-root-value",
  locked_execution: "old-root-value",
  settings: {conditional_execution: "old-settings-value"},
  local_settings: {conditional_execution: "old-local-value"},
  groups: [{
    id: "group-1", mode: "basic", conditional_execution: "old-group-value",
    locked_execution: "old-group-value",
  }],
};
const sanitized = FTTestConfigurationCompiler.sanitizeExecutionPayload(
  conditionalManifest, stalePayload, basicValues,
);
assert.equal(sanitized.settings, undefined);
assert.equal(sanitized.local_settings, undefined);
assert.equal("conditional_execution" in sanitized, false);
assert.equal("conditional_authoring" in sanitized, false);
assert.equal(sanitized.locked_execution, "automatic");
assert.equal("conditional_execution" in sanitized.groups[0], false);
assert.equal("conditional_authoring" in sanitized.groups[0], false);
assert.equal(sanitized.groups[0].locked_execution, "automatic");

const subjects = FTTestConfigurationCompiler.factorSubjects([factor]);
assert.deepEqual(subjects, [{
  ...factor,
}]);
const nested = frozenFactor("c", "Nested|N:5d", "Nested");
assert.deepEqual(
  FTTestConfigurationCompiler.factorSubjects([{
    ...factor, factor_dependencies: [nested, nested],
  }]),
  [nested, factor],
);
const nestedInline = {
  ...nested,
  temporary: true,
  source_kind: "transient",
  source_origin: "test_inline",
  source_code: "class Nested: pass\n",
};
assert.deepEqual(
  FTTestConfigurationCompiler.factorSubjects([{
    ...factor, factor_dependencies: [nestedInline],
  }]),
  [nestedInline, factor],
);
assert.deepEqual(
  FTTestConfigurationCompiler.factorSubjects([factor, structuredClone(factor)]),
  [factor],
);
assert.throws(
  () => FTTestConfigurationCompiler.factorSubjects([
    factor, {...factor, alias: "conflicting"},
  ]),
  /不同的冻结对象/,
);
assert.throws(
  () => FTTestConfigurationCompiler.factorSubjects([{alias: "unfrozen"}]),
  /缺少稳定引用/,
);
assert.throws(
  () => FTTestConfigurationCompiler.factorSubjects([{
    alias: "UploadedMomentum|N:5d", source_kind: "transient",
  }]),
  /缺少稳定引用/,
);

const another = frozenFactor("b", "SgCCS|N:20d|$F:1m", "SgCCS");
const configurationGroup = {
  config_group_id: "icg-day-roc",
  batch_id: "icb-day-roc",
  name: "日盘 ROC",
  factor_ref: factor.ref,
  product_scope_ref: "product-group:day",
  entry_delay_bars: 1,
  horizon: {sampling: "explicit", bases: ["signal", "1m"], multipliers: [1, 5]},
  methods: ["rank", "pearson"],
  return_price_basis: "next_open_to_open_adjusted",
  editor_mounted_tabs: ["__configuration__", "factor", "product_path_selection"],
};
const analysis = FTICConfiguration.compileAnalysis({
  prior: {product_path_selections: [{product_path_selection_id: "stale"}]},
  manifest,
  values,
  configurationGroups: [configurationGroup],
  productCatalog: [{...product, product_path_selection_id: "product-group:day"}],
});
assert.equal(analysis.schema_version, 2);
assert.deepEqual(analysis.configuration_groups, [configurationGroup]);
assert.deepEqual(analysis.product_selections, {
  "product-group:day": {product_path_selection_id: "product-group:day"},
});
assert.equal(analysis.paths, undefined);
assert.equal(analysis.settings, undefined);
assert.equal("product_path_selection_id" in analysis, false);
assert.equal("product_path_selection" in analysis, false);
assert.equal("factors" in analysis, false);
assert.equal("product_path_selections" in analysis, false);
assert.deepEqual(analysis.execution.settings, {
  category: "industry",
  custom_product_fields: [{product: "SI.GFE", field: "margin", value: 0.12}],
  start_date: "2025-01-02",
});
assert.equal("ic_lags" in analysis.execution.settings, false);
assert.equal("forward_return_horizons" in analysis.execution.settings, false);
assert.equal("ic_decay_lags" in analysis.execution.settings, false);
assert.equal("editor_mounted_tabs" in analysis.configuration_groups[0], true);

assert.throws(() => FTICConfiguration.compileAnalysis({
  manifest, values, configurationGroups: [], productCatalog: [],
}), /exactly one configuration group/);

console.log("ok");
