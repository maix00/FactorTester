const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/core/output-choices.js", "utf8",
), {filename: "output-choices.js"});
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/jobs/generation.js", "utf8",
), {filename: "generation.js"});

const capabilities = [
  {name: "ic_series", analyses: ["ic"], before_run: true, after_run: true, default: true},
  {name: "ic_statistics", analyses: ["ic"], before_run: true, after_run: true, default: true},
  {name: "equity_curve", analyses: ["backtest"], before_run: true, after_run: true},
];
assert.deepEqual(
  window.FTOutputChoices.initialSelection(capabilities, "ic", null),
  ["ic_series", "ic_statistics"],
);
assert.deepEqual(
  window.FTOutputChoices.initialSelection(capabilities, "ic", []),
  [],
);
assert.deepEqual(
  window.FTOutputChoices.initialSelection(
    capabilities, "backtest", ["ic_series", "equity_curve"],
  ),
  ["equity_curve"],
);
assert.equal(window.FTJobGeneration.analysisOf({job: {kind: "ic_test"}}, {}), "ic");
assert.equal(window.FTJobGeneration.analysisOf({job: {kind: "group_backtest"}}, {}), "backtest");
assert.equal(window.FTJobGeneration.batchCount([
  {name: "equity", supplemental_bundle: "time_series"},
  {name: "returns", supplemental_bundle: "time_series"},
  {name: "orders", supplemental_bundle: "execution_account"},
], ["equity", "returns", "orders"]), 2);
console.log("ok");
