const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
const factor = {
  factor_alias: "ROC", factor_ref: "factor:v1:roc", family_ref: "family:v1:roc",
};
global.FTTestFactors = {
  selectedFactor: state => state.noOuterFactor ? null : factor,
  selectedFamily: () => ({factor_family_alias: "MmRateOfChg", family_ref: "family:v1:roc"}),
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
  factorSubjects: () => [{alias: "ROC", factor_ref: "factor:v1:roc"}],
};
global.FTTestRunFields = {selection: () => [{name: "ic_statistics_data"}]};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/ic-configuration.js", "utf8",
), {filename: "ic-configuration.js"});
global.FTICConfiguration = window.FTICConfiguration;
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {filename: process.argv[2]});

const requests = [];
const state = {
  kind: "ic", manifest: {defaults: {}}, values: {
    factor_candidates: [{
      ...factor, temporary: true, source_origin: "test_inline",
    }],
    category_candidates: [{
      id: "inline-category:session", temporary: true, title_zh: "会话分类",
    }],
  },
  factors: [factor], families: [], groups: [{
    id: "inline-product-group:session", temporary: true,
    paths: ["CNFutures/**"],
  }, {
    group_ref: "product-group:persisted", name: "持久产品组",
    paths: ["CNFutures/day/**"],
  }], analysis: {}, settingsMountedTabs: ["factor", "delay"],
  factorRef: factor.factor_ref, groupRef: "day", groupRefs: ["day"],
  outputCapabilities: [], outputRequests: [],
  transientFactorSources: [{
    factor_id: "InlineFactor", path: "inline/InlineFactor.py",
    source_code: "class InlineFactor: pass\n",
  }],
  workspace: {workspace_id: "workspace-1", configuration: {revision: 1, payload: {}}},
};
const context = {t: value => value, api: async (path, options) => {
  requests.push({path, body: JSON.parse(options.body)});
  return {configuration: {revision: 2, payload: JSON.parse(options.body).payload}};
}};

(async () => {
  await window.FTTestConfiguration.save(context, state, {id: "day", paths: ["CNFutures"]});
  assert.deepEqual(
    requests[0].body.payload.ui.ic.mounted_tabs,
    ["factor", "delay"],
  );
  const temporary = requests[0].body.payload.shared.temporary_objects;
  assert.equal(temporary.factors[0].factor_ref, factor.factor_ref);
  assert.equal(temporary.product_groups[0].id, "inline-product-group:session");
  assert.equal(temporary.categories[0].id, "inline-category:session");
  assert.equal(temporary.factor_sources[0].factor_id, "InlineFactor");

  const backtestState = {
    ...state,
    kind: "backtest",
    analysis: {
      groups: [{
        id: "strategy-1",
        factor_candidate_refs: ["factor:v1:roc"],
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
      configuration: {revision: 1, payload: {}},
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
