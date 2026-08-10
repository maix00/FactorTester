const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.FTTestProducts = {
  selectedGroups: state => state.groups,
  groupID: group => group.id,
  groupLabel: group => group.label,
};
let revision = 0;
global.FTTestConfiguration = {
  async save(_context, state, group) {
    revision += 1;
    state.workspace = state.workspace || {workspace_id: "workspace-one"};
    return {revision, group_id: group.id};
  },
};
global.FTReferencePage = {
  routeFor: (kind, target) => `/reference?kind=${kind}&target=${target}`,
};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/workbench/test-run-fields.js", "utf8",
), {filename: "test-run-fields.js"});
global.FTTestRunFields = window.FTTestRunFields;

vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/workbench/ic-run-batch.js", "utf8",
), {filename: "ic-run-batch.js"});

const requests = [];
let navigated = false;
const context = {
  t: value => value,
  servicePath: path => `/service${path}`,
  navigate: () => { navigated = true; },
  async api(path, options) {
    requests.push({path, body: JSON.parse(options.body)});
    const index = requests.filter(item => item.path.endsWith("/api/runs")).length;
    if (path.endsWith("/preview")) {
      return {run_spec_hash: `${"a".repeat(63)}${requests.length}`};
    }
    return {
      port: 8141,
      run: {run_id: `run-${index}`, run_spec_hash: `${"b".repeat(63)}${index}`},
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
};

(async () => {
  const batch = window.FTICRunBatch;
  assert.deepEqual(batch.synchronize(state).map(item => item.groupID), ["day", "night"]);
  await batch.previewAll(context, state, () => {});
  assert.deepEqual(state.icRunBatch.map(item => item.phase), ["frozen", "frozen"]);
  assert.ok(state.icRunBatch.every(item => item.runSpecHash.length === 64));

  await batch.runAll(context, state, () => {});
  assert.deepEqual(state.icRunBatch.map(item => item.jobID), ["job-1", "job-2"]);
  assert.deepEqual(state.icRunBatch.map(item => item.port), [8141, 8141]);
  assert.equal(batch.jobPath(state.icRunBatch[0]), "/jobs/8141/job-1");
  assert.match(batch.runSpecPath(state.icRunBatch[0]), /^\/reference\?kind=run-spec/);
  assert.equal(navigated, false, "batch submission must keep the IC page visible");
  assert.equal(requests.filter(item => item.path.endsWith("/api/runs")).length, 2);
  assert.ok(requests.every(item => item.body.retention_mode === "full"));
  assert.ok(requests.every(item => (
    JSON.stringify(item.body.output_requests) === JSON.stringify(["ic_series", "ic_statistics"])
  )));
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
