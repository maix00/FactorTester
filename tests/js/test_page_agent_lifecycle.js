const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/profile/page-agent-lifecycle.js", "utf8"),
  {filename: "page-agent-lifecycle.js"},
);

(async () => {
  const calls = [];
  const lifecycle = window.FTPageAgentLifecycle.create({
    start: async profileID => calls.push(["start", profileID]),
    stop: async profileID => calls.push(["stop", profileID]),
  });

  await lifecycle.open("profile-a", "report-tab");
  await lifecycle.open("profile-a", "factor-tab");
  lifecycle.hide("profile-a", "report-tab");
  assert.deepEqual(calls, [["start", "profile-a"]], "hiding does not stop the Agent");

  await lifecycle.evict("report-tab");
  assert.deepEqual(calls, [["start", "profile-a"]], "another owning tab keeps it running");
  await lifecycle.evict("factor-tab");
  assert.deepEqual(calls, [
    ["start", "profile-a"], ["stop", "profile-a"],
  ], "the final tab eviction stops the Agent");

  console.log("PASS: page Agent lifetime follows profile tab ownership");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
