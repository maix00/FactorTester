const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {
  FTTestProducts: {
    groupID: value => value?.group_ref || value?.id || "",
    groupLabel: value => value?.title_zh || value?.name || value?.id || "",
  },
};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "strategy-editor-scope.js",
});

const state = {
  settingsMountedTabs: ["factor", "product_path_selection"],
  factors: [{ref: "visible-factor", alias: "Visible"}],
  groups: [{group_ref: "visible-group", title_zh: "Visible group"}],
  values: {
    factor_candidates: [{ref: "outer-factor", alias: "Outer"}],
    factor: "outer-factor",
    product_path_candidates: [{group_ref: "outer-group", title_zh: "Outer group"}],
    product_path_selection: "outer-group",
  },
  manifest: {
    strategy_editor: {
      outer_scope_tabs: {
        factor: {
          mounted_tab: "factor", candidate_fields: ["factor_candidates"],
          selection_fields: ["factor_candidates"],
        },
        product_path_selection: {
          mounted_tab: "product_path_selection", candidate_fields: ["product_path_candidates"],
          selection_fields: ["product_path_selections", "product_path_selection"],
        },
      },
      scoped_fields: {
        factor_candidates: {
          label: "因子候选",
          inner: {
            cardinality: "many",
            filter_only_when_outer_mounted: true,
            source_when_outer_mounted: "outer_candidate_pool",
          },
        },
        factor_role_bindings: {
          inner: {visible_when: {min_items: {factor_candidates: 2}}},
        },
      },
      inner_default_tabs: [
        {key: "__strategy__", label: "分组"},
        {key: "factor", label: "因子执行"},
        {key: "product_path_selection", label: "产品组"},
      ],
      outer_only_tabs: ["time", "data_source"],
    },
    defaults: {
      time_field: {tab_key: "time", scope_policy: "overridable", execution_policy: "include"},
      fee_mode: {tab_key: "cost", scope_policy: "overridable", execution_policy: "include"},
    },
    tab_lists: {"group-settings": [
      {key: "time", label: "时间"}, {key: "cost", label: "成本"},
    ]},
  },
};

const sourceState = {
  values: {data_source_mode: "list", data_source: ["source-a"]},
  manifest: {strategy_editor: {candidate_constraints: {
    category_candidates: {
      source_field: "data_source", mode_field: "data_source_mode",
      automatic_mode: "auto", coverage: "complete_path_coverage",
    },
    product_path_candidates: {
      source_field: "data_source", mode_field: "data_source_mode",
      automatic_mode: "auto", coverage: "complete_product_coverage",
    },
  }}},
};
const compatibleGroup = {products: [
  {source_ids: ["source-a", "source-b"]}, {source_ids: ["source-a"]},
]};
const incompleteGroup = {products: [
  {source_ids: ["source-a"]}, {source_ids: ["source-b"]},
]};
assert.equal(window.FTStrategyEditorScope.candidateCompatible(
  sourceState, "product_path_candidates", compatibleGroup,
), true);
assert.equal(window.FTStrategyEditorScope.candidateCompatible(
  sourceState, "product_path_candidates", incompleteGroup,
), false);
assert.equal(window.FTStrategyEditorScope.candidateCompatible(
  sourceState, "category_candidates", {items: [
    {source_ids: ["source-a"]}, {source_ids: ["source-b"]},
  ]},
), false);
sourceState.values.data_source_mode = "auto";
assert.equal(window.FTStrategyEditorScope.candidateCompatible(
  sourceState, "product_path_candidates", incompleteGroup,
), true);
sourceState.values.data_source_mode = "list";
sourceState.values.data_source = [];
assert.equal(window.FTStrategyEditorScope.candidateCompatible(
  sourceState, "product_path_candidates", compatibleGroup,
), false);

if (process.argv[3]) {
  state.manifest = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
}

assert.equal(window.FTStrategyEditorScope.scope(state, "factor").items[0].ref, "outer-factor");
assert.equal(window.FTStrategyEditorScope.scope(state, "product_path_selection").items[0].group_ref, "outer-group");
assert.deepEqual(window.FTStrategyEditorScope.validate(state), []);
const innerCandidates = window.FTStrategyEditorScope.scopedField(
  state, "factor_candidates", "inner",
);
assert.equal(innerCandidates?.cardinality, "many");
assert.equal(innerCandidates?.filter_only_when_outer_mounted, true);
assert.equal(innerCandidates?.source_when_outer_mounted, "outer_candidate_pool");
assert.equal(
  window.FTStrategyEditorScope.scopedField(state, "factor", "outer"),
  null,
);
assert.equal(
  window.FTStrategyEditorScope.fieldVisible(
    state, "factor_role_bindings", "inner", {factor_candidates: [{alias: "A"}]},
  ),
  false,
);
assert.equal(
  window.FTStrategyEditorScope.fieldVisible(
    state, "factor_role_bindings", "inner",
    {factor_candidates: [{alias: "A"}, {alias: "B"}]},
  ),
  true,
);
const fallbackCombinationRequired = window.FTStrategyEditorScope.fieldRequired(
  state, "factor_combination_mode", "inner", {
    factor_candidates: [{alias: "A"}, {alias: "B"}],
  },
);
assert.equal(
  fallbackCombinationRequired,
  process.argv[3] ? true : null,
  "the backend contract supplies the combination requirement when provided",
);
if (process.argv[3]) {
  const combination = window.FTStrategyEditorScope.scopedField(
    state, "factor_combination_mode", "inner",
  );
  assert.equal(combination?.options?.length, 0);
  assert.equal(
    window.FTStrategyEditorScope.fieldRequired(
      state, "factor_combination_mode", "inner", {
        factor_candidates: [{alias: "A"}, {alias: "B"}],
      },
    ),
    true,
  );
  assert.equal(
    window.FTStrategyEditorScope.fieldVisible(
      state, "warmup_window", "inner", {warmup_mode: "fixed"},
    ),
    true,
  );
  assert.equal(
    window.FTStrategyEditorScope.fieldVisible(
      state, "warmup_window", "inner", {warmup_mode: "auto"},
    ),
    false,
  );
  assert.equal(
    window.FTStrategyEditorScope.scopedField(
      state, "product_path_candidates", "inner",
    )?.source_when_outer_unmounted,
    "visible_product_group_catalog",
  );
}
state.values.factor = "";
state.values.product_path_selection = "";
assert.equal(window.FTStrategyEditorScope.validate(state).length, 0);
state.values.factor_candidates = [];
assert.equal(window.FTStrategyEditorScope.validate(state).length, 1);
state.values.product_path_candidates = [];
assert.equal(window.FTStrategyEditorScope.validate(state).length, 2);
state.settingsMountedTabs = [];
assert.equal(window.FTStrategyEditorScope.scope(state, "factor").items[0].ref, "visible-factor");
assert.equal(window.FTStrategyEditorScope.scope(state, "factor").required, false);
assert.deepEqual(
  window.FTStrategyEditorScope.innerTabs(state, ["cost", "time"])
    .map(item => item.key),
  ["__strategy__", "factor", "product_path_selection", "cost"],
);
assert.equal(
  window.FTStrategyEditorScope.innerTabs(state, ["data_source"])
    .some(item => item.key === "data_source"),
  false,
);
console.log("ok");
