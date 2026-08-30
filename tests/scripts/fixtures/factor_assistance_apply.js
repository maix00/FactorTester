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
window.FTFactorAssistance.register({}, {
  state,
  name: control(""), chineseName: control(""),
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
  source: {mode: "source", code: "class ProbeMin: pass\n"},
  parameter_values: {N: "25d"},
});
assert.equal(state.sourceCode, "class ProbeMin: pass\n");
assert.equal(dirtyKey, "source");
assert.equal(redraws, 1);

vm.runInThisContext(
  fs.readFileSync("server/manager/web/catalog/factor-editor.js", "utf8"),
  {filename: "factor-editor.js"},
);
assert.deepStrictEqual(
  window.FTFactorEditor.reconcileParameterValues([
    {alias: "$F", default_value: "1m"},
    {alias: "$Rev", default_value: "0"},
  ], {N: "25d", "$F": "5m"}),
  {$F: "5m", $Rev: "0"},
  "source validation must discard parameters not declared by the new source",
);
console.log("ok");
