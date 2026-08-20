const assert = require("assert").strict;
const fs = require("fs");

global.window = globalThis;
global.structuredClone = global.structuredClone || (value => JSON.parse(JSON.stringify(value)));

const source = process.argv[2];
eval(fs.readFileSync(
  "server/manager/web/workbench/setting-rules.js", "utf8",
));
eval(fs.readFileSync(source, "utf8"));
eval(fs.readFileSync(
  "server/manager/web/workbench/ic-configuration.js", "utf8",
));

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
const factor = {
  factor_ref: "factor:v1:profile-maxa:path:alias:commit:blob",
  factor_alias: "ROC|N:20d|$F:1d",
  factor_family_alias: "ROC",
};
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
    split_count: 5,
    settings: {split_count: 5},
    local_settings: {split_count: 5},
    groups: [{id: "group-1", split_count: 5}],
  },
  values,
);
assert.equal("split_count" in scopedPayload, false);
assert.equal("split_count" in scopedPayload.settings, false);
assert.equal("split_count" in scopedPayload.local_settings, false);
assert.equal(scopedPayload.groups[0].split_count, 5);

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
for (const value of [sanitized.settings, sanitized.local_settings]) {
  assert.equal("conditional_execution" in value, false);
  assert.equal("conditional_authoring" in value, false);
}
assert.equal("conditional_execution" in sanitized, false);
assert.equal("conditional_authoring" in sanitized, false);
assert.equal(sanitized.locked_execution, "automatic");
assert.equal("conditional_execution" in sanitized.groups[0], false);
assert.equal("conditional_authoring" in sanitized.groups[0], false);
assert.equal(sanitized.groups[0].locked_execution, "automatic");

const subjects = FTTestConfigurationCompiler.factorSubjects([factor]);
assert.deepEqual(subjects, [{
  alias: factor.factor_alias,
  factor_ref: factor.factor_ref,
}]);
assert.throws(
  () => FTTestConfigurationCompiler.factorSubjects([{factor_alias: "unfrozen"}]),
  /缺少稳定引用/,
);
assert.deepEqual(
  FTTestConfigurationCompiler.factorSubjects([{
    factor_alias: "UploadedMomentum|N:5d",
    source_kind: "transient",
    transient_factor_id: "UploadedMomentum",
  }]),
  [{alias: "UploadedMomentum|N:5d"}],
);

const another = {
  factor_ref: "factor:v1:profile-maxa:path:other:commit:blob",
  factor_alias: "SgCCS|N:20d|$F:1m",
  factor_family_alias: "SgCCS",
};
const analysis = FTICConfiguration.compileAnalysis({
  prior: {product_path_selections: [{product_path_selection_id: "stale"}]},
  manifest,
  values,
  factors: [factor, another],
  productSelection: product,
  fallbackFamilyAlias: "ROC",
});
assert.equal(analysis.product_path_selection_id, "day");
assert.deepEqual(analysis.paths, ["CNFutures/day"]);
assert.deepEqual(analysis.factors, [
  {alias: factor.factor_alias, factor_ref: factor.factor_ref},
  {alias: another.factor_alias, factor_ref: another.factor_ref},
]);
assert.equal("product_path_selections" in analysis, false);
assert.equal("factor_family_alias" in analysis, false);
assert.deepEqual(analysis.ic_lags, [0, 1]);
assert.deepEqual(analysis.settings, analysis.local_settings);

const oneFamily = FTICConfiguration.compileAnalysis({
  prior: {}, manifest, values, factors: [factor], productSelection: product,
});
assert.equal("factor_family_alias" in oneFamily, false);

console.log("ok");
