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
    path.join(root, "server/manager/web/core/highcharts-range-loader.js"),
    "utf8",
  ),
  context,
);
vm.runInContext(
  fs.readFileSync(
    path.join(root, "server/manager/web/core/price-chart.js"),
    "utf8",
  ),
  context,
);

const target = {classList: {add() {}}};
const lazyRange = {loadRange() {}, rangeOptions() { return {series: []}; }};
const result = context.FTPriceChart.render({t: value => value}, target, {
  product: "SI.GFE",
  desc: "工业硅",
  freq: "DAY1",
  data: [
    {timestamp: "2025-01-02T15:00:00+08:00", open: 10, high: 12, low: 9, close: 11, volume: 100, open_interest: 80},
    {timestamp: 1735897200000, open: 11, high: 13, low: 10, close: 12, volume: 120, open_interest: 90},
  ],
}, lazyRange);

assert.strictEqual(result, chart);
assert.strictEqual(captured.target, target);
assert.strictEqual(captured.options.navigator.enabled, true);
assert.strictEqual(captured.options.scrollbar.enabled, true);
assert.strictEqual(captured.options.chart.panning.enabled, true);
assert.strictEqual(captured.options.chart.height, 650);
assert.strictEqual(captured.options.chart.zooming.type, "x");
assert.strictEqual(captured.options.series[0].type, "candlestick");
assert.strictEqual(captured.options.series[1].name, "成交量");
assert.strictEqual(captured.options.series[2].name, "持仓量");
assert.strictEqual(captured.options.series[0].data.length, 2);
assert.ok(Number.isFinite(captured.options.series[0].data[0][0]));
assert.ok(captured.options.rangeSelector.buttons.length >= 5);
assert.strictEqual(captured.options.rangeSelector.allButtonsEnabled, true);
assert.strictEqual(captured.options.navigator.adaptToUpdatedData, false);
assert.strictEqual(captured.options.chart.zooming.mouseWheel.showResetButton, true);
const zhDate = captured.options.xAxis.labels.formatter.call({value: 1735812000000});
assert.ok(zhDate.includes("2025"));
const tooltip = captured.options.series[0].tooltip.pointFormatter.call({
  open: 10, high: 12, low: 9, close: 11,
});
assert.ok(tooltip.includes("开盘价"));
assert.ok(tooltip.includes("最高价"));
assert.ok(tooltip.includes("最低价"));
assert.ok(tooltip.includes("收盘价"));
const volumeTooltip = captured.options.series[1].tooltip.pointFormatter.call({y: 100});
const openInterestTooltip = captured.options.series[2].tooltip.pointFormatter.call({y: 80});
assert.ok(volumeTooltip.endsWith("<br/>"));
assert.ok(openInterestTooltip.endsWith("<br/>"));
const localized = context.FTPriceChart.render({
  locale: "en",
  t(value) {
    return {
      "开盘价": "Open price", "最高价": "High price",
      "最低价": "Low price", "收盘价": "Close price",
      "成交量": "Volume", "持仓量": "Open interest",
    }[value] || value;
  },
}, target, {product: "SI.GFE", data: [
  {timestamp: 1735897200000, open: 11, high: 13, low: 10, close: 12, volume: 120, open_interest: 90},
]});
assert.strictEqual(localized, chart);
const enDate = captured.options.xAxis.labels.formatter.call({value: 1735812000000});
assert.ok(enDate.includes("2025"));
assert.notStrictEqual(enDate, zhDate);
const localizedTooltip = captured.options.series[0].tooltip.pointFormatter.call({
  open: 11, high: 13, low: 10, close: 12,
});
assert.ok(localizedTooltip.includes("Open price"));
console.log("ok");
