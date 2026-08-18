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
  factors: [{factor_ref: "visible-factor", factor_alias: "Visible"}],
  groups: [{group_ref: "visible-group", title_zh: "Visible group"}],
  values: {
    factor_candidates: [{factor_ref: "outer-factor", factor_alias: "Outer"}],
    factor: "outer-factor",
    product_path_candidates: [{group_ref: "outer-group", title_zh: "Outer group"}],
    product_path_selection: "outer-group",
  },
  manifest: {
    strategy_editor: {
      outer_scope_tabs: {
        factor: {
          mounted_tab: "factor", candidate_fields: ["factor_candidates"],
          selection_fields: ["factor_selections", "factor"],
        },
        product_path_selection: {
          mounted_tab: "product_path_selection", candidate_fields: ["product_path_candidates"],
          selection_fields: ["product_path_selections", "product_path_selection"],
        },
      },
      inner_default_tabs: [
        {key: "__strategy__", label: "分组"},
        {key: "factor", label: "因子执行"},
        {key: "product_path_selection", label: "产品组"},
      ],
      outer_only_tabs: ["time"],
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

assert.equal(window.FTStrategyEditorScope.scope(state, "factor").items[0].factor_ref, "outer-factor");
assert.equal(window.FTStrategyEditorScope.scope(state, "product_path_selection").items[0].group_ref, "outer-group");
assert.deepEqual(window.FTStrategyEditorScope.validate(state), []);
state.values.factor = "";
state.values.product_path_selection = "";
assert.equal(window.FTStrategyEditorScope.validate(state).length, 2);
state.settingsMountedTabs = [];
assert.equal(window.FTStrategyEditorScope.scope(state, "factor").items[0].factor_ref, "visible-factor");
assert.equal(window.FTStrategyEditorScope.scope(state, "factor").required, false);
assert.deepEqual(
  window.FTStrategyEditorScope.innerTabs(state, ["cost", "time"])
    .map(item => item.key),
  ["__strategy__", "factor", "product_path_selection", "cost"],
);
console.log("ok");
