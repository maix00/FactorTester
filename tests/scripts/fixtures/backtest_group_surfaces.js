const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
const groups = [{id: "strategy-1"}];
global.FTBacktestGroupModel = {
  initialize() {},
  selected: () => groups,
  removeSelected: () => groups.splice(0),
};
global.FTConfigurationGroupSurface = {
  register(kind, renderer) { this.kind = kind; this.renderer = renderer; },
  render(options) { this.options = options; return options; },
};
global.FTStrategyLibraryRuntime = {factorStrategies: async () => ({families: [], items: []})};
global.FTTestProducts = {projection: value => value};

vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-groups.js",
});

const state = {
  kind: "backtest",
  analysis: {
    groups,
    factor_strategy_bindings: [{strategy_id: "strategy-1"}],
    strategy_venue_bindings: [{strategy_id: "strategy-1"}],
  },
  strategyBindings: [{target_strategy_id: "strategy-1"}],
  manifest: {surfaces: [{key: "groups", content_adapter: "backtest_groups"}]},
};
const context = {t: value => value};
const rendered = window.FTBacktestGroups.render(context, state, () => {});
assert.equal(rendered.title, "策略组");
assert.equal(rendered.adapters.backtest_groups.actions.create().mode, "family");
assert.deepEqual(Object.keys(rendered.adapters), ["backtest_groups"],
  "the page has one strategy-group surface, not separate long-short/custom-strategy pages");
assert.equal(rendered.emptyTitle, "暂无策略");

rendered.adapters.backtest_groups.removeSelected(state);
assert.equal(state.analysis.groups.length, 0);
assert.equal(state.analysis.factor_strategy_bindings.length, 0);
assert.equal(state.analysis.strategy_venue_bindings.length, 0);
assert.equal(state.strategyBindings.length, 0);
console.log("ok");
