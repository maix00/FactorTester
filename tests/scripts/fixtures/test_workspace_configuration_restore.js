const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = global.structuredClone
  || (value => JSON.parse(JSON.stringify(value)));

function load(path) {
  vm.runInThisContext(fs.readFileSync(path, "utf8"), {filename: path});
}

function frozenFactor(digest, alias, family, params = {}) {
  return {
    schema_version: 2, ref: `factor:v2:${digest.repeat(43)}`, alias,
    owner_ref: "profile:maxa",
    identity: {
      family_ref: `factor-family:v2:${digest.toUpperCase().repeat(43)}`,
      family_alias: family,
      family_formula_fingerprint: digest.repeat(64),
      self_formula_fingerprint: digest.repeat(64), params,
    },
  };
}

const nestedFactor = frozenFactor("c", "SgChgPct|P:[CA]|M:0.6|B:1|N:200d|$F:1d", "SgChgPct");
const topFactor = frozenFactor("a", "SgChgDur|P:[CA]|Th:[SgChgPct]|K:30m|$F:1m", "SgChgDur", {
  Th: nestedFactor.ref,
});
const topFactorWithDeps = {
  ...topFactor,
  factor_dependencies: [nestedFactor],
};

load("server/manager/web/workbench/test-lazy-code.js");
global.FTTestLazyCode = window.FTTestLazyCode;
load("server/manager/web/workbench/configuration-groups/ic/model.js");
global.FTICConfigurationGroupModel = window.FTICConfigurationGroupModel;
load("server/manager/web/workbench/test-state.js");

// factor_evaluation: savedFactors arrive in dependency-first order (nested first,
// top-level last) because factorSubjects() visits dependencies before their owner.
// applyWorkspaceConfiguration must restore state.factorRef to the top-level factor
// recorded in analyses.factor_evaluation.factor_ref, not to savedFactors[0].
{
  const state = {
    kind: "factor_evaluation",
    manifest: {run_fields: []},
    workspace: {
      workspace_id: "workspace-fe",
      configuration: {payload: {
        shared: {factors: [nestedFactor, topFactor]},
        analyses: {factor_evaluation: {
          factor_ref: topFactor.ref,
          factor_alias: topFactor.alias,
          factor_family_alias: topFactor.identity.family_alias,
          paths: ["Product/Futures/CNFutures/_products/AP.CZC"],
          product_path_selection_id: "product-group:pg_day",
        }},
        ui: {factor_evaluation: {}},
      }},
    },
    values: {},
  };
  window.FTTestState.applyWorkspaceConfiguration(state);
  assert.equal(
    state.factorRef, topFactor.ref,
    "factor_evaluation must restore factorRef from analysis.factor_ref, not savedFactors[0]",
  );
  assert.equal(state.savedFactors.length, 2);
  assert.equal(state.savedFactors[0].ref, nestedFactor.ref);
  assert.equal(state.savedFactors[1].ref, topFactor.ref);
}

// backtest: same dependency-first ordering, factor_ref lives in analysis.groups[0].factor_candidate_refs
{
  const state = {
    kind: "backtest",
    manifest: {run_fields: []},
    workspace: {
      workspace_id: "workspace-bt",
      configuration: {payload: {
        shared: {factors: [nestedFactor, topFactor]},
        analyses: {backtest: {
          groups: [{
            id: "group-1",
            factor_candidate_refs: [topFactor.ref],
            product_path_selection_id: "product-group:pg_day",
          }],
        }},
        ui: {backtest: {}},
      }},
    },
    values: {},
  };
  window.FTTestState.applyWorkspaceConfiguration(state);
  assert.equal(
    state.factorRef, topFactor.ref,
    "backtest must restore factorRef from analysis groups, not savedFactors[0]",
  );
}

// factor_evaluation without analysis.factor_ref falls back to savedFactors[0]
// (legacy compatibility for very old payloads).
{
  const state = {
    kind: "factor_evaluation",
    manifest: {run_fields: []},
    workspace: {
      workspace_id: "workspace-fe-legacy",
      configuration: {payload: {
        shared: {factors: [nestedFactor, topFactor]},
        analyses: {factor_evaluation: {}},
        ui: {factor_evaluation: {}},
      }},
    },
    values: {},
  };
  window.FTTestState.applyWorkspaceConfiguration(state);
  assert.equal(
    state.factorRef, nestedFactor.ref,
    "legacy payload without analysis.factor_ref falls back to savedFactors[0]",
  );
}

console.log("ok");
