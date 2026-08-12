const assert = require("assert").strict;
const fs = require("fs");

global.window = globalThis;
global.structuredClone = global.structuredClone || (value => JSON.parse(JSON.stringify(value)));

const source = process.argv[2];
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
assert.equal("stale_unknown_field" in execution, false);

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
assert.equal(oneFamily.factor_family_alias, "ROC");

console.log("ok");
