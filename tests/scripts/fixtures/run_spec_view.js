const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/research/run-spec-view.js", "utf8",
), {filename: "run-spec-view.js"});

const view = window.FTRunSpecView;
const hash = "a".repeat(64);
const value = view.model({
  run_spec_hash: hash,
  run_spec_version: 2,
  configuration_id: "configuration-1",
  configuration_revision: 7,
  alias_zh: "日盘 IC 运行配置",
  summary_zh: "两个因子、三个收益期",
  run_spec: {
    workspace_id: "workspace-1",
    configuration_fingerprint: "fingerprint-1",
    analyses: ["ic"],
    retention_mode: "full",
    configuration: {shared: {start_date: "2025-01-01"}, analyses: {ic: {ic_lags: [0, 1]}}},
  },
});

assert.equal(value.identity.run_spec_hash, hash);
assert.equal(value.identity.configuration_revision, 7);
assert.equal(value.identity.workspace_id, "workspace-1");
assert.deepEqual(value.configuration.analyses.ic.ic_lags, [0, 1]);
assert.deepEqual(value.execution, {analyses: ["ic"], retention_mode: "full"});
assert.equal(value.title, "日盘 IC 运行配置");
assert.equal(value.summary, "两个因子、三个收益期");
assert.equal(view.digest(`runspec:sha256:${hash}`), hash);
assert.equal(view.digest(`run-spec:sha256:${hash}`), hash);
assert.equal(view.digest("invalid"), "");
console.log("ok");
