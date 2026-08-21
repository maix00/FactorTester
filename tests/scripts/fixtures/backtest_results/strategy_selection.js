const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "strategy-selection.js",
});

const strategies = [
  {id: "strategy-a", label: "同名策略", configurationID: "config-a"},
  {id: "strategy-b", label: "同名策略", configurationID: "config-b"},
];
const api = window.FTBacktestStrategySelection;
assert.deepEqual(api.normalize([], strategies), [api.ALL_STRATEGIES]);
assert.equal(api.items(strategies)[0].exclusive, true);
assert.equal(api.items(strategies)[0].label, "全部策略");
const scope = api.createScope(strategies, ["strategy-b"]);
assert.deepEqual(scope.filterPayload({
  series: [
    {strategy_id: "strategy-a", label: "同名策略"},
    {strategy_id: "strategy-b", label: "同名策略"},
  ],
  rows: [
    {strategy_id: "strategy-a", value: 1},
    {strategy_id: "strategy-b", value: 2},
    {series: "__aggregate__", value: 3},
  ],
}), {
  series: [{strategy_id: "strategy-b", label: "同名策略"}],
  rows: [
    {strategy_id: "strategy-b", value: 2},
    {series: "__aggregate__", value: 3},
  ],
});
console.log("ok");
