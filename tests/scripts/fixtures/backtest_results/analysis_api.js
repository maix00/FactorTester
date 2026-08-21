const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.setTimeout = callback => { callback(); return 0; };
global.FTJobArtifacts = {
  async fetch(_context, path) {
    calls.push({path, artifact: true});
    return {async text() { return JSON.stringify(
      path.includes("ranking") ? {period_count: 1} : {summary: {}},
    ); }};
  },
};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-analysis-api.js",
});

const calls = [];
const context = {
  async api(path, options) {
    calls.push({path, options, payload: options?.body ? JSON.parse(options.body) : null});
    if (path.includes("supplementals/child-detail")) {
      return {success: true, job: {status: "succeeded"}, result_summary: {
        artifact_name: "strategy-analysis--detail",
      }};
    }
    if (path.includes("supplementals/child-ranking")) {
      return {success: true, job: {status: "succeeded"}, result_summary: {
        artifact_name: "strategy-analysis--ranking",
      }};
    }
    if (path.includes("supplementals")) {
      const tab = JSON.parse(options.body).params.analysis_tab;
      return {success: true, job: {job_id: tab === "ranking" ? "child-ranking" : "child-detail"}};
    }
    return {success: true, groups: []};
  },
};
const options = {
  jobID: "job/a", portQuery: "?port=8180",
  artifactQuery: "?server_id=remote-main",
};

(async () => {
  const detail = await window.FTBacktestAnalysisAPI.detail(context, options, {
    job_id: "must-be-overridden", group_index: 2,
  });
  assert.deepEqual(detail, {summary: {}});
  assert.equal(calls[0].path, "/api/jobs/job%2Fa/supplementals?server_id=remote-main");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(calls[0].payload, {
    kind: "backtest_strategy_analysis",
    params: {job_id: "must-be-overridden", group_index: 2},
  });
  assert.equal(calls[1].path, "/api/jobs/job%2Fa/supplementals/child-detail?server_id=remote-main");
  assert.equal(calls[2].path, "/api/jobs/job%2Fa/artifacts/strategy-analysis--detail?server_id=remote-main");

  const ranking = await window.FTBacktestAnalysisAPI.ranking(context, options, {
    product_path_selection_id: "night",
  });
  assert.deepEqual(ranking, {period_count: 1});
  assert.equal(calls[3].path, "/api/jobs/job%2Fa/supplementals?server_id=remote-main");
  assert.equal(calls[3].payload.params.analysis_tab, "ranking");

  await window.FTBacktestAnalysisAPI.snapshot(context, options, {timestamp_ms: 1});
  await window.FTBacktestAnalysisAPI.orderFlow(context, options, {group_id: "g1"});
  assert.equal(calls[6].path, "/api/jobs/job%2Fa/group-snapshot?port=8180");
  assert.equal(calls[7].path, "/api/jobs/job%2Fa/group-order-flow?port=8180");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
