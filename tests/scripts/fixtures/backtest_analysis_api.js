const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-analysis-api.js",
});

const calls = [];
const context = {
  async api(path, options) {
    calls.push({path, options, payload: JSON.parse(options.body)});
    if (path.includes("group-detail")) return {success: true, detail: {summary: {}}};
    if (path.includes("group-ranking-detail")) return {success: true, detail: {period_count: 1}};
    return {success: true, groups: []};
  },
};
const options = {jobID: "job/a", portQuery: "?port=8180"};

(async () => {
  const detail = await window.FTBacktestAnalysisAPI.detail(context, options, {
    job_id: "must-be-overridden", group_index: 2,
  });
  assert.deepEqual(detail, {summary: {}});
  assert.equal(calls[0].path, "/api/jobs/job%2Fa/group-detail?port=8180");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(calls[0].payload, {job_id: "must-be-overridden", group_index: 2});

  const ranking = await window.FTBacktestAnalysisAPI.ranking(context, options, {
    product_path_selection_id: "night",
  });
  assert.deepEqual(ranking, {period_count: 1});
  assert.equal(calls[1].path, "/api/jobs/job%2Fa/group-ranking-detail?port=8180");

  await window.FTBacktestAnalysisAPI.snapshot(context, options, {timestamp_ms: 1});
  await window.FTBacktestAnalysisAPI.orderFlow(context, options, {group_id: "g1"});
  assert.equal(calls[2].path, "/api/jobs/job%2Fa/group-snapshot?port=8180");
  assert.equal(calls[3].path, "/api/jobs/job%2Fa/group-order-flow?port=8180");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
