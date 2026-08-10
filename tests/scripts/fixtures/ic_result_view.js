const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "ic-result-view.js",
});
const artifacts = [
  {name: "ic_series_data", state: "active"},
  {name: "ic_statistics_data", state: "active"},
  {name: "ic_series_report", state: "active"},
  {name: "ic_rolling_stability_data", state: "deleted"},
];
assert.equal(window.FTICResults.supports(artifacts), true);
assert.deepEqual(
  window.FTICResults.relevantArtifacts(artifacts).map(item => item.name),
  ["ic_series_data", "ic_statistics_data"],
);
assert.equal(window.FTICResults.supports([
  {name: "equity_curve_data", state: "active"},
]), false);
console.log("ok");
