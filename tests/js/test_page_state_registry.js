const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/core/page-state.js", "utf8"),
  {filename: "page-state.js"},
);

const durable = {};
let selectedTab = "source";
let source = "class Momentum: pass";
const first = window.FTPageState.create({durable});
first.register("factor-editor", {
  capture: () => ({selectedTab, source}),
  restore: value => {
    selectedTab = value.selectedTab;
    source = value.source;
  },
  describe: () => ({
    page: "factor-create",
    section: selectedTab,
    fields: [{key: "source", editable: true, value: source}],
  }),
});
first.capture();

selectedTab = "wrong";
source = "";
const restored = window.FTPageState.create({durable});
restored.register("factor-editor", {
  capture: () => ({selectedTab, source}),
  restore: value => {
    selectedTab = value.selectedTab;
    source = value.source;
  },
  describe: () => ({
    page: "factor-create",
    section: selectedTab,
    fields: [{key: "source", editable: true, value: source}],
  }),
  apply: action => {
    if (action.field !== "source") return false;
    source = String(action.value);
    return true;
  },
});

assert.equal(selectedTab, "source");
assert.equal(source, "class Momentum: pass");
assert.deepEqual(restored.describe(), {
  schema_version: 1,
  sections: [{
    id: "factor-editor",
    page: "factor-create",
    section: "source",
    fields: [{key: "source", editable: true, value: "class Momentum: pass"}],
  }],
});
assert.equal(restored.apply("factor-editor", {field: "source", value: "class Revised: pass"}), true);
assert.equal(source, "class Revised: pass");
restored.capture();
assert.equal(durable.pageState.sections["factor-editor"].source, "class Revised: pass");

console.log("PASS: registered page state survives a tab view rebuild");
