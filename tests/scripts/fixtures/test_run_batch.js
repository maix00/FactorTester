const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
let actionLoaded = false;
const lazyGroups = [];
const actionsSource = fs.readFileSync(
  "server/manager/web/workbench/run-batch/actions.js", "utf8",
);
global.window.FTStaticLoader = {
  async loadGroups(names) {
    lazyGroups.push(...names);
    if (names.includes("workbench-run-batch-actions") && !actionLoaded) {
      window.FTTestConfiguration = global.FTTestConfiguration;
      vm.runInThisContext(actionsSource, {filename: "run-batch/actions.js"});
      actionLoaded = true;
    }
  },
};
global.FTTestProducts = {
  selectedGroups: state => state.groups,
  groupID: group => group.id,
  groupLabel: group => group.label,
};
window.FTTestProducts = global.FTTestProducts;
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-lazy-code.js", "utf8",
), {filename: "test-lazy-code.js"});
let revision = 0;
global.FTTestConfiguration = {
  async save(_context, state, group) {
    revision += 1;
    state.workspace = state.workspace || {workspace_id: "workspace-one"};
    return {
      revision, group_id: group.id,
      configuration_id: `configuration-${revision}`,
    };
  },
};
global.FTReferencePage = {
  routeFor: (kind, target) => `/reference?kind=${kind}&target=${target}`,
};
global.FTTestInputState = {
  requestBody: state => ({
    transient_factor_sources: state.transientFactorSources || [],
    transient_strategy_sources: state.transientStrategySources || [],
    strategy_specs: state.strategySpecs || [],
  }),
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-run-fields.js", "utf8",
), {filename: "test-run-fields.js"});
global.FTTestRunFields = window.FTTestRunFields;

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/run-batch/model.js", "utf8",
), {filename: "run-batch/model.js"});

vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-run-batch.js", "utf8",
), {filename: "test-run-batch.js"});

const requests = [];
const previewRequests = [];
let navigated = false;
let openedRunSpecs = [];
const notices = [];
window.FTRunSpecView = {
  openMany: (_context, entries) => { openedRunSpecs = entries; },
};
const context = {
  t: value => value,
  servicePath: path => `/service${path}`,
  navigate: () => { navigated = true; },
  showNotice: (message, isError) => { notices.push({message, isError}); },
  button: (label, action, help) => {
    const button = {
    textContent: label, title: help, className: "", disabled: false,
    listeners: {click: action},
    addEventListener: (name, callback) => { button.listeners[name] = callback; },
    };
    return button;
  },
  async api(path, options) {
    const body = JSON.parse(options.body);
    requests.push({path, body});
    if (path.includes("/configuration-snapshots")) {
      const snapshotNumber = requests.filter(item => (
        item.path.includes("/configuration-snapshots")
      )).length;
      return {
        success: true,
        snapshot: {
          snapshot_id: `snapshot-${snapshotNumber}`,
          snapshot_revision: 1,
        },
      };
    }
    const index = requests.filter(item => item.path.endsWith("/api/runs")).length;
    if (path.endsWith("/preview")) {
      const hash = `${"a".repeat(63)}${requests.length}`;
      previewRequests.push({body, hash});
      return {
        run_spec_hash: hash,
        run_spec_version: 3,
        configuration_id: "configuration-preview",
        configuration_revision: requests.length,
        report_projection: {run_spec: {
          target_ref: `runspec:sha256:${hash}`,
          alias_zh: "预览运行配置",
          summary_zh: "预览",
          complete_parameters: {
            run_spec_version: 3,
            configuration: {shared: {workspace_id: "workspace-one"}},
            analyses: [state?.kind || "ic"],
          },
        }},
      };
    }
    return {
      port: 8141,
      server_id: "public-1",
      run: {
        run_id: `run-${index}`,
        run_spec_hash: previewRequests.find(item => (
          JSON.stringify(item.body) === JSON.stringify(body)
        ))?.hash || `${"b".repeat(63)}${index}`,
      },
      jobs: [{job_id: `job-${index}`}],
    };
  },
};
const state = {
  kind: "ic",
  workspace: {workspace_id: "workspace-one"},
  groups: [
    {id: "day", label: "日盘"},
    {id: "night", label: "夜盘"},
  ],
  outputRequests: ["ic_series", "ic_statistics"],
  manifest: {run_fields: [
    {
      key: "retention_mode", default: "summary", request_location: "body",
      placement: "run_options", order: 10,
    },
    {
      key: "output_requests", default: [], request_location: "body",
      placement: "outputs", order: 20,
    },
  ]},
  runValues: {retention_mode: "full"},
  transientFactorSources: [{
    factor_id: "UploadedMomentum",
    path: "custom_factors/UploadedMomentum.py",
    source_code: "class UploadedMomentum: pass\n",
  }],
  transientStrategySources: [],
  strategySpecs: [],
};

const backtest = {
  ...state,
  kind: "backtest",
  groups: [{id: "all", label: "全部产品"}],
  analysis: {
    groups: [{
      id: "default-strategy",
      factorAlias: "DynamicHold",
      product_path_selection_id: "all",
      product_path_selection: {
        product_path_selection_id: "all",
        selected_paths: ["CNFutures/**"],
      },
    }],
    ls_configs: [],
  },
  outputRequests: ["equity_curve"],
  runValues: {retention_mode: "summary"},
  transientFactorSources: [],
  transientStrategySources: [{
    path: "strategies/dynamic_hold.py",
    source_code: "class DynamicHold: pass\n",
  }],
  strategySpecs: [{
    strategy_id: "DynamicHold",
    source: "profile:strategies/dynamic_hold.py",
  }],
};

const factorEvaluation = {
  ...backtest,
  kind: "factor_evaluation",
  groups: [{id: "all", label: "全部产品"}],
  outputRequests: ["factor_series"],
};

const strategyScopedBacktest = {
  ...backtest,
  groups: [],
  analysis: {
    groups: [{
      id: "strategy-1",
      factorAlias: "DynamicHold",
      product_path_selection_id: "strategy-products",
      product_path_selection: {
        product_path_selection_id: "strategy-products",
        selected_paths: ["CNFutures/**"],
      },
    }, {
      id: "strategy-2",
      factorAlias: "DynamicHold",
      product_path_selection_id: "other-strategy-products",
      product_path_selection: {
        product_path_selection_id: "other-strategy-products",
        selected_paths: ["USFutures/**"],
      },
    }],
    ls_configs: [],
  },
};

(async () => {
  const batch = window.FTTestRunBatch;
  assert.equal(actionLoaded, false, "submission code must not load while creating header actions");
  assert.deepEqual(batch.synchronize(state).map(item => item.groupID), ["day", "night"]);
  assert.equal(state.activeRunGroupID, "day");
  let cleared = 0;
  window.FTTests = {clearDraft: () => { cleared += 1; }};
  const header = batch.headerActions(context, state, () => {});
  assert.deepEqual(header.map(item => item.textContent), ["查看运行配置", "运行", "清空"]);
  assert.equal(header[0].disabled, false);
  assert.equal(header[1].disabled, false);
  header[2].listeners.click();
  assert.equal(cleared, 1);
  const emptyHeader = batch.headerActions(context, {...state, groups: []}, () => {});
  assert.equal(emptyHeader[0].disabled, false,
    "view RunSpec must remain clickable without a product group");
  assert.equal(emptyHeader[1].disabled, true,
    "run action stays disabled without a product group");
  emptyHeader[0].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.ok(notices.some(item => item.isError && /请先选择产品组/.test(item.message)),
    "missing product selection must be explained by the header action");

  const lateState = {...state, groups: [], testRunBatch: []};
  let lateRuns = 0;
  window.FTTestRunBatchActions = {
    async runAll() { lateRuns += 1; },
  };
  const lateHeader = batch.headerActions(context, lateState, () => {});
  lateState.groups = [{id: "late", label: "延迟加载产品组"}];
  lateHeader[1].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(lateRuns, 1,
    "run action must read the current task scope instead of captured render-time state");

  window.FTTestRunBatchActions = {
    async runAll() { throw new Error("submission module failed"); },
  };
  batch.headerActions(context, state, () => {})[1].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.ok(notices.some(item => item.isError && /submission module failed/.test(item.message)),
    "run action failures must be visible instead of becoming unhandled rejections");
  delete window.FTTestRunBatchActions;

  await batch.previewAll(context, state, () => {});
  assert.deepEqual(state.testRunBatch.map(item => item.phase), ["frozen", "frozen"]);
  assert.ok(state.testRunBatch.every(item => item.runSpecHash.length === 64));

  const nestedPreviewItem = {phase: "freezing", runSpecHash: ""};
  batch.recordPreview(nestedPreviewItem, {
    report_projection: {run_spec: {
      target_ref: `runspec:sha256:${"c".repeat(64)}`,
    }},
  });
  assert.equal(nestedPreviewItem.runSpecHash, "c".repeat(64),
    "RunSpec references from the report projection must be normalized");
  assert.throws(
    () => batch.recordPreview({phase: "freezing", runSpecHash: ""}, {success: true}),
    /缺少有效 RunSpec 哈希/,
    "a successful response without a RunSpec reference must not look frozen");

  const frozenHeader = batch.headerActions(context, state, () => {});
  frozenHeader[0].listeners.click();
  assert.deepEqual(openedRunSpecs.map(item => item.label), ["任务 1 · 日盘", "任务 2 · 夜盘"],
    "view run configuration must open one overlay tab per task");
  assert.ok(openedRunSpecs.every(item => /^runspec:sha256:/.test(item.target)),
    "overlay tabs must use the frozen RunSpec references");
  assert.ok(openedRunSpecs.every(item => item.value?.run_spec),
    "preview RunSpecs must be available to the overlay without persistence");
  assert.match(frozenHeader[1].title, /全部任务/,
    "the header run action must submit the complete task batch");

  const refreshResetState = {
    ...backtest,
    testRunBatch: [],
  };
  const resetHeader = batch.headerActions(context, refreshResetState, () => {
    refreshResetState.testRunBatch = [];
  });
  resetHeader[0].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(openedRunSpecs.some(item => item.label.includes("回测任务")),
    "RunSpec overlay must use the returned frozen record across a UI refresh");
  assert.equal(refreshResetState.testRunBatch[0]?.phase, "frozen",
    "preview must repopulate the current batch model after content refresh");
  assert.equal(resetHeader[0].disabled, false,
    "preview action must recover after the overlay opens");
  assert.equal(resetHeader[1].disabled, false,
    "successful preview must restore Run even when refresh rebuilt batch state");

  delete window.FTRunSpecView;
  const previousLoader = window.FTStaticLoader.loadGroups;
  window.FTStaticLoader.loadGroups = async names => {
    lazyGroups.push(...names);
    if (names.includes("research-reference")) {
      window.FTRunSpecView = {
        openMany: (_context, entries) => { openedRunSpecs = entries; },
      };
    }
  };
  openedRunSpecs = [];
  const deferredViewerState = {...backtest, testRunBatch: []};
  batch.headerActions(context, deferredViewerState, () => {})[0].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(lazyGroups.includes("research-reference"),
    "RunSpec preview must load the module group that owns its overlay");
  assert.ok(openedRunSpecs.some(item => item.label.includes("回测任务")),
    "deferred RunSpec viewer must open after its module loads");
  window.FTStaticLoader.loadGroups = previousLoader;

  const failingContext = {
    ...context,
    async api() {
      const error = new Error("preview endpoint unavailable");
      error.code = "no_capable_service";
      error.details = {detail: "required source is unavailable"};
      error.candidates = [{server_id: "office-a", port: 8141, detail: "offline"}];
      throw error;
    },
  };
  const failingState = {
    ...state,
    groups: [{id: "broken", label: "故障产品组"}],
    testRunBatch: [],
  };
  const failingHeader = batch.headerActions(failingContext, failingState, () => {});
  failingHeader[0].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(notices.some(item => item.isError && /preview endpoint unavailable/.test(item.message)),
    "RunSpec preview failures must be visible instead of being swallowed");
  assert.ok(notices.some(item => item.isError
    && /no_capable_service/.test(item.message)
    && /required source is unavailable/.test(item.message)
    && /office-a:8141/.test(item.message)
    && /offline/.test(item.message)),
  "RunSpec preview failures must expose structured backend diagnostics");

  const refreshDropsBatchState = () => { failingState.testRunBatch = []; };
  notices.length = 0;
  const refreshedFailureHeader = batch.headerActions(
    failingContext, failingState, refreshDropsBatchState,
  );
  refreshedFailureHeader[0].listeners.click();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(notices.some(item => item.isError
    && /preview endpoint unavailable/.test(item.message)
    && /required source is unavailable/.test(item.message)),
  "preview diagnostics must survive a render that rebuilds batch state");

  const failedRunHeader = batch.headerActions(failingContext, failingState, () => {});
  failedRunHeader[1].listeners.click();
  assert.equal(failedRunHeader[1].disabled, true,
    "run action must disable itself while the submission is pending");
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(failedRunHeader[1].disabled, false,
    "a rejected submission must restore the run action without a full page render");
  assert.ok(notices.some(item => item.isError && /运行测试失败/.test(item.message)));

  await batch.runAll(context, state, () => {});
  assert.deepEqual(state.testRunBatch.map(item => item.jobID), ["job-1", "job-2"]);
  assert.deepEqual(batch.submittedItems(state).map(item => item.jobID), ["job-1", "job-2"],
    "submitted jobs must remain available to the test-page progress/result observer");
  assert.equal(state.activeRunGroupID, "night");
  assert.deepEqual(state.testRunBatch.map(item => item.port), [8141, 8141]);
  assert.equal(batch.jobPath(state.testRunBatch[0]), "/jobs/8141/job-1?server_id=public-1");
  assert.match(batch.runSpecPath(state.testRunBatch[0]), /^\/reference\?kind=run-spec/);

  assert.deepEqual(batch.synchronize(backtest).map(item => item.groupID), ["__backtest__"]);
  await batch.previewAll(context, backtest, () => {});
  assert.equal(backtest.testRunBatch[0].groupLabel, "回测任务");
  assert.match(backtest.testRunBatch[0].runSpecHash, /^[a-f0-9]{64}$/,
    "backtest preview must persist a RunSpec before submission");
  const backtestPreviewRequest = requests.filter(item => (
    item.path.endsWith("/preview")
  )).at(-1).body;
  await batch.runAll(context, backtest, () => {});
  assert.equal(backtest.testRunBatch[0].jobID, "job-3");
  assert.equal(batch.jobPath(backtest.testRunBatch[0]), "/jobs/8141/job-3?server_id=public-1");
  assert.equal(requests.at(-1).body.analyses[0], "backtest");
  assert.equal(requests.at(-1).body.retention_mode, "summary");
  assert.deepEqual(requests.at(-1).body.output_requests, ["equity_curve"]);
  assert.equal(requests.at(-1).body.transient_strategy_sources[0].path,
    "strategies/dynamic_hold.py");
  assert.equal(requests.at(-1).body.strategy_specs[0].strategy_id, "DynamicHold");
  assert.deepEqual(requests.at(-1).body, backtestPreviewRequest,
    "formal submission must reuse the exact preview request");
  assert.equal(requests.filter(item => item.path.endsWith("/preview"))[0]
    .body.transient_factor_sources[0].factor_id,
    "UploadedMomentum");
  assert.deepEqual(batch.synchronize(factorEvaluation).map(item => item.groupID), ["all"]);
  await batch.runAll(context, factorEvaluation, () => {});
  assert.equal(factorEvaluation.testRunBatch[0].jobID, "job-4");
  const factorEvaluationPreview = requests.filter(item => (
    item.path.endsWith("/preview") && item.body.analyses[0] === "factor_evaluation"
  )).at(-1).body;
  assert.deepEqual(requests.at(-1).body, factorEvaluationPreview,
    "direct run must freeze and submit the exact same RunSpec request");
  assert.equal(requests.at(-1).body.analyses[0], "factor_evaluation");

  assert.deepEqual(batch.synchronize(strategyScopedBacktest)
    .map(item => item.groupID), ["__backtest__"],
  "strategy-owned product scopes must create one backtest task");
  assert.equal(strategyScopedBacktest.testRunBatch[0].groupLabel, "回测任务");
  await batch.runAll(context, strategyScopedBacktest, () => {});
  assert.equal(strategyScopedBacktest.testRunBatch[0].jobID, "job-5");
  assert.equal(requests.at(-1).body.analyses[0], "backtest");

  const refreshDuringSubmission = {
    ...strategyScopedBacktest,
    testRunBatch: [],
  };
  await batch.previewAll(context, refreshDuringSubmission, () => {});
  await batch.runAll(context, refreshDuringSubmission, () => {
    refreshDuringSubmission.testRunBatch = refreshDuringSubmission.testRunBatch
      .map(item => ({...item}));
  });
  assert.equal(refreshDuringSubmission.testRunBatch[0].jobID, "job-6",
    "submission must publish the Job identity after a repaint replaces batch entries");
  assert.deepEqual(batch.submittedItems(refreshDuringSubmission).map(item => item.jobID), ["job-6"],
    "a repainted test page must retain the Job consumed by its progress/result observer");
  assert.equal(navigated, false, "submission must keep the test page visible");
  assert.equal(requests.filter(item => item.path.endsWith("/api/runs")).length, 6);
  assert.ok(actionsSource.includes("state.runValues?.service_port"));
  assert.ok(actionsSource.includes(
    'serviceRunPath(context, state, "/api/runs/preview")',
  ));
  assert.ok(actionsSource.includes(
    'submitServerRun(context, state, request)',
  ));
  assert.ok(actionsSource.includes("controller.abort()"));
  assert.ok(actionsSource.includes("FTJobs?.invalidate?.()"),
    "server submissions must invalidate the cached task-list pages");
  assert.equal(actionLoaded, true, "the first explicit action loads submission code");
  assert.ok(lazyGroups.includes("workbench-run-batch-actions"));
  assert.ok(!lazyGroups.includes("research"),
    "submitting a test must not wait for the unrelated report/profile/research UI bundle");
  const runRequests = requests.filter(item => item.path.endsWith("/api/runs"));
  const icRequests = runRequests.filter(item => item.body.analyses[0] === "ic");
  assert.ok(icRequests.every(item => item.body.retention_mode === "full"));
  assert.ok(icRequests.every(item => (
    JSON.stringify(item.body.output_requests) === JSON.stringify(["ic_series", "ic_statistics"])
  )));
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
