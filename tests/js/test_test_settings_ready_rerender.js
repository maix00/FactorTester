const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = globalThis;
window.location = {search: ""};
global.FTTestSettings = {
  initialMountedTabs: () => ["run"],
  initialValues: () => ({engine: "default"}),
};
global.FTTestContentAdapters = {};
global.FTSettingRules = {};
global.FTTestState = {
  savedMountedTabs: () => [], savedSettings: () => ({}),
  restoreTemporaryObjects: () => {},
};
global.FTTestLazyCode = {
  ensureGroupCode: () => { throw new Error("ready code must not reload"); },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/workbench/tests.js", "utf8"),
  {filename: "tests.js"},
);

(async () => {
  const state = {
    manifest: {}, values: null, settingsInitialized: false,
    settingsCode: {status: "ready", error: "", promise: null},
  };
  let insideLoadingRender = true;
  let refreshes = 0;
  const promise = FTTests.ensureSettingsCode({}, state, () => {
    assert.equal(insideLoadingRender, false,
      "the completed page must render after the stale loading pass commits");
    refreshes += 1;
  });
  assert.equal(state.settingsInitialized, true);
  assert.equal(refreshes, 0, "ready settings do not synchronously re-enter render");
  insideLoadingRender = false;
  await promise;
  await Promise.resolve();
  assert.equal(refreshes, 1);
  console.log("PASS: cached test settings cannot be overwritten by a stale loading render");
})().catch(error => { console.error(error); process.exitCode = 1; });
