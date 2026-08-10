const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "../../..");
let captured = null;
const chart = {destroyed: false, destroy() { this.destroyed = true; }};
const context = {
  window: {},
  Highcharts: {
    stockChart(target, options) {
      captured = {target, options};
      return chart;
    },
  },
  console,
};
context.window = context;
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(
    path.join(root, "scripts/worktree_manager_web/core/price-chart.js"),
    "utf8",
  ),
  context,
);

const target = {classList: {add() {}}};
const result = context.FTPriceChart.render({t: value => value}, target, {
  product: "SI.GFE",
  desc: "工业硅",
  freq: "DAY1",
  data: [
    {timestamp: "2025-01-02T15:00:00+08:00", open: 10, high: 12, low: 9, close: 11, volume: 100, open_interest: 80},
    {timestamp: 1735897200000, open: 11, high: 13, low: 10, close: 12, volume: 120, open_interest: 90},
  ],
});

assert.strictEqual(result, chart);
assert.strictEqual(captured.target, target);
assert.strictEqual(captured.options.navigator.enabled, true);
assert.strictEqual(captured.options.scrollbar.enabled, true);
assert.strictEqual(captured.options.chart.panning.enabled, true);
assert.strictEqual(captured.options.chart.zooming.type, "x");
assert.strictEqual(captured.options.series[0].type, "candlestick");
assert.strictEqual(captured.options.series[1].name, "成交量");
assert.strictEqual(captured.options.series[2].name, "持仓量");
assert.strictEqual(captured.options.series[0].data.length, 2);
assert.ok(Number.isFinite(captured.options.series[0].data[0][0]));
assert.ok(captured.options.rangeSelector.buttons.length >= 5);
console.log("ok");
