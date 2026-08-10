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
const context = {
  t: value => value,
  api: async (path, options) => {
    requests.push({path, options});
    return {workspace: {workspace_id: "workspace-restored"}};
  },
  navigate: path => routes.push(path),
};

(async () => {
  await FTJobActions.cloneRunWorkspace(context, {
    job: {kind: "group_backtest", run_id: "run-123"},
    portQuery: "?port=8141",
    title: "恢复配置",
    derivedPrefill: {parentID: "group-1", products: ["SI.GFE"]},
  });
  assert.equal(requests[0].path, "/api/runs/run-123/clone-workspace?port=8141");
  assert.deepEqual(JSON.parse(requests[0].options.body), {title: "恢复配置"});
  assert.equal(local.get("ft-backtest-workspace"), "workspace-restored");
  assert.deepEqual(JSON.parse(session.get("ft-backtest-derived-prefill")), {
    workspaceID: "workspace-restored", parentID: "group-1", products: ["SI.GFE"],
  });
  assert.deepEqual(routes, ["/backtest"]);
  assert.equal(FTJobActions.workbenchKind({kind: "ic_test"}), "ic");
  assert.equal(FTJobActions.workbenchKind({kind: "unknown"}), "");
  console.log("ok");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
