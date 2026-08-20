const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {location: {search: ""}};
global.document = {};
global.structuredClone = value => JSON.parse(JSON.stringify(value));
global.FTTestState = {
  savedMountedTabs: () => [],
  savedSettings: () => ({}),
};
global.FTTestLazyCode = {
  ensureGroupCode: () => Promise.resolve(),
};
global.FTSettingRules = {};
global.FTTestContentAdapters = {};
window.FTSettingRules = global.FTSettingRules;
window.FTTestContentAdapters = global.FTTestContentAdapters;
global.FTTestSettings = window.FTTestSettings = {
  initialMountedTabs: () => ["engine"],
  initialValues: () => ({engine: "native"}),
};

const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInThisContext(source, {filename: process.argv[2]});

// A late lazy/progress callback belongs to the route token that created it.
// Once the user changes tabs it must not touch the shared page content.
const staleContent = {replaceChildren() { throw new Error("stale route repainted content"); }};
assert.doesNotThrow(() => window.FTTests.render({
  isRouteCurrent: () => false,
  content: staleContent,
}, {}));

let refreshes = 0;
const state = {
  manifest: {},
  settingsCode: {status: "ready", error: "", promise: null},
  settingsInitialized: false,
};
window.FTTests.ensureSettingsCode({}, state, () => { refreshes += 1; });

assert.equal(state.settingsInitialized, true,
  "a ready loader record must still initialize a new test session");
assert.deepEqual(state.settingsMountedTabs, ["engine"]);
assert.deepEqual(state.values, {engine: "native"});
assert.equal(refreshes, 1,
  "recovering a ready-but-uninitialized session should repaint once");

const preloadedState = {
  manifest: {},
  settingsCode: {status: "idle", error: "", promise: null},
  settingsInitialized: false,
};
window.FTTests.ensureSettingsCode({}, preloadedState, () => { refreshes += 1; })
  .then(() => {
    assert.equal(preloadedState.settingsInitialized, true,
      "a preloaded settings module must still repaint a new test session");
    assert.equal(refreshes, 2);
    // The field controls may arrive through another lazy group before the
    // schema script.  Loading a tab in that state must render an error rather
    // than dereference FTTestSettingsSchema or create an unhandled rejection.
    window.FTTestSettingFields = {};
    const incompleteState = {
      settingsFieldsCode: {status: "ready", error: "", promise: null},
      settingsTabLoads: Object.create(null),
    };
    return window.FTTests.ensureSettingsTab({}, incompleteState, "engine", () => {})
      .then(() => {
        assert.equal(incompleteState.settingsFieldsCode.status, "error");
        assert.equal(incompleteState.settingsTabLoads.engine.status, "error");
        assert.match(incompleteState.settingsTabLoads.engine.error, /字段模块/);
        console.log("ok");
      });
  })
  .catch(error => {
    console.error(error);
    process.exitCode = 1;
  });
