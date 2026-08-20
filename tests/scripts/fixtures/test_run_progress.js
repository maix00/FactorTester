const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
let watched = null;
let refreshes = 0;
window.FTTestRunResults = {
  refresh: () => { refreshes += 1; },
};
let stopped = 0;
window.FTJobProgress = {
  progressView: (_context, status) => ({
    root: {status}, bar: {}, label: {},
  }),
  stopProgress: () => { stopped += 1; },
  watchProgress: async (_context, _jobID, _query, _view, options) => {
    watched = options;
    options.onPayload({status: "running"});
    options.onPayload({event: "result", data: {}});
    options.onComplete();
  },
};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/test-run-progress.js", "utf8",
), {filename: "test-run-progress.js"});

const item = {
  jobID: "job-1", portQuery: "?port=8141", serverID: "public-1", phase: "submitted",
};
let rerenders = 0;
(async () => {
  const root = window.FTTestRunProgress.render({}, {}, item, () => { rerenders += 1; });
  assert.equal(root.status, "submitted");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(item.phase, "succeeded");
  assert.ok(watched);
  assert.equal(stopped, 2, "a terminal payload must close the live progress stream");
  assert.equal(refreshes, 1);
  assert.equal(rerenders, 0);
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
