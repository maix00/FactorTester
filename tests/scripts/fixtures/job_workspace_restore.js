const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const local = new Map();
const session = new Map();
global.localStorage = {
  getItem: key => local.get(key) || null,
  setItem: (key, value) => local.set(key, String(value)),
};
global.sessionStorage = {
  getItem: key => session.get(key) || null,
  setItem: (key, value) => session.set(key, String(value)),
  removeItem: key => session.delete(key),
};
global.window = globalThis;
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "actions.js",
});

const requests = [];
const routes = [];
const tabs = [];
const context = {
  t: value => value,
  api: async (path, options) => {
    requests.push({path, options});
    return {workspace: {workspace_id: "workspace-restored"}};
  },
  navigate: path => routes.push(path),
  openTab: (path, options) => tabs.push({path, options}),
};

(async () => {
  await FTJobActions.cloneRunWorkspace(context, {
    job: {kind: "group_backtest", run_id: "run-123"},
    portQuery: "?port=8141",
    title: "恢复配置",
    jobID: "job-123", resolvedPort: 8141, serverID: "public-1",
    openNewTab: true,
    derivedPrefill: {parentID: "group-1", products: ["SI.GFE"]},
  });
  assert.equal(requests[0].path, "/api/runs/run-123/clone-workspace?port=8141");
  assert.deepEqual(JSON.parse(requests[0].options.body), {title: "恢复配置"});
  assert.equal(local.has("ft-backtest-workspace"), false);
  assert.deepEqual(JSON.parse(session.get("ft-backtest-derived-prefill")), {
    workspaceID: "workspace-restored", parentID: "group-1", products: ["SI.GFE"],
  });
  assert.deepEqual(routes, []);
  assert.equal(tabs.length, 1);
  assert.equal(tabs[0].options.forceNew, true);
  const opened = new URL(tabs[0].path, "http://factortester.invalid");
  assert.equal(opened.pathname, "/backtest");
  assert.equal(opened.searchParams.get("workspace_id"), "workspace-restored");
  assert.equal(opened.searchParams.get("job_id"), "job-123");
  assert.equal(opened.searchParams.get("server_id"), "public-1");
  assert.equal(FTJobActions.workbenchKind({kind: "ic_test"}), "ic");
  assert.equal(FTJobActions.workbenchKind({kind: "unknown"}), "");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
