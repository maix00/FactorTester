"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

let adapter = null;
global.window = {};
global.FTPageAssistance = {
  register(_context, value) { adapter = value; return {}; },
};
vm.runInThisContext(
  fs.readFileSync("server/manager/web/core/factor-param-contract.js", "utf8"),
  {filename: "factor-param-contract.js"},
);
vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-assistance.js", "utf8"),
  {filename: "factor-assistance.js"},
);

const state = {
  mode: "create", familyMode: true, sourceMode: "source",
  sourceCode: "", parameterValues: {N: "25d"},
};
const control = value => ({value});
let dirtyKey = "";
let redraws = 0;
const nameControl = control("");
window.FTFactorAssistance.register({}, {
  state,
  name: nameControl, chineseName: control(""),
  description: control(""), category: control(""),
  tabs: {current: () => "source"},
  redraw: () => { redraws += 1; },
  markDirty: eventOrKey => {
    dirtyKey = typeof eventOrKey === "string"
      ? eventOrKey : eventOrKey.target.dataset.tabKey;
  },
});

adapter.importDocument({
  name: "ProbeMin", chinese_name: "探针", description: "", category: "自编",
  source: {mode: "source", code: "class PendingSourceName: pass\n"},
  parameter_values: {N: "25d"},
});
assert.equal(state.sourceCode, "class PendingSourceName: pass\n");
assert.equal(
  nameControl.value, "ProbeMin",
  "assistance must restore the draft field without deriving it from source",
);
assert.equal(dirtyKey, "source");
assert.equal(redraws, 1);
const schema = adapter.schema();
assert.match(schema.properties.parameter_values.description, /FactorParam/);
assert.equal(
  schema["x-factor-tester-factor-param-contract"].inline_from_source.source_kind,
  "transient",
);
assert.match(
  schema["x-factor-tester-factor-param-contract"].signal_align,
  /forward-fill/,
);

console.log("ok");
