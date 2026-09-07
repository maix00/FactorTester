const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "../../..");
let captured = null;
let capturedDisplayOptions = null;
const chart = {xAxis: [{}], destroyed: false, destroy() { this.destroyed = true; }};
const context = {
  window: {}, console,
  Highcharts: {
    stockChart(target, options) { captured = {target, options}; return chart; },
  },
};
context.window = context;
context.FTJobHighcharts = {
  mountOptions(_context, target, options, stock, displayOptions) {
    assert.strictEqual(stock, true);
    captured = {target, options};
    capturedDisplayOptions = displayOptions;
    return chart;
  },
};
vm.createContext(context);
[
  "server/manager/web/core/price-chart.js",
  "server/manager/web/core/market-data.js",
  "server/manager/web/jobs/highcharts-timeline.js",
  "server/manager/web/test-modules/factor-evaluation/results/model.js",
  "server/manager/web/test-modules/factor-evaluation/results/chart.js",
  "server/manager/web/test-modules/factor-evaluation/results/view.js",
].forEach(file => vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), context));

const result = {
  factor: {alias: "MmRateOfChg|P:[CA]|N:20d|$F:1d", freq: "DAY1"},
  products: [{name: "SI.GFE", desc: "工业硅"}],
  series: [{
    product: "SI.GFE", desc: "工业硅",
    dates: ["2025-01-02T15:00:00+08:00", "2025-01-03T15:00:00+08:00"],
    values: [0.1, 0.2],
  }],
};
const model = context.FTFactorSeriesModel.build({result});
assert.strictEqual(model.series.length, 1);
assert.strictEqual(context.FTFactorSeriesModel.label(model.series[0]), "SI.GFE · 工业硅");
assert.strictEqual(context.FTFactorSeriesModel.points(model.series[0]).length, 2);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(context.FTFactorSeriesModel.priceRequest({
    payload: {analyses: {factor_evaluation: {execution: {settings: {
      frequency: "MIN5", price_type: "raw", start_date: "2025-01-01",
    }}}}},
  }, "SI.GFE"))),
  {product_name: "SI.GFE", freq: "MIN5", adjusted: false, start_date: "2025-01-01"},
);
assert.strictEqual(context.FTMarketData.rangeContextMs("MIN1"), 604800000);
assert.strictEqual(context.FTMarketData.rangeContextMs("HOUR1"), 604800000);
assert.strictEqual(context.FTMarketData.rangeContextMs("DAY1"), 0);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(context.FTMarketData.rangeRequest(
    {product_name: "SI.GFE", freq: "MIN1"},
    new Date(2025, 0, 2, 9, 30).getTime(),
    new Date(2025, 0, 2, 10, 30).getTime(), 900,
  ))),
  {
    product_name: "SI.GFE", freq: "MIN1",
    start_date: "2025-01-02", start_time: "09:30:00",
    end_date: "2025-01-02", end_time: "10:30:00", max_points: 900,
  },
);

const target = {replaceChildren() {}, classList: {add() {}}};
const mounted = context.FTFactorSeriesChart.mount({t: value => value}, target, {
  product: "SI.GFE", factorLabel: result.factor.alias,
  factorSeries: result.series[0],
  price: {data: [
    {timestamp: "2025-01-02T15:00:00+08:00", open: 10, high: 12, low: 9, close: 11, volume: 100, open_interest: 80},
    {timestamp: "2025-01-03T15:00:00+08:00", open: 11, high: 13, low: 10, close: 12, volume: 120, open_interest: 90},
  ]},
  contracts: [{contract: "SI2501", start: "2025-01-01", end: "2025-01-31"}],
});
assert.strictEqual(mounted, chart);
assert.deepStrictEqual(JSON.parse(JSON.stringify(captured.options.series.map(item => item.type))), [
  "candlestick", "line", "column", "line",
]);
assert.strictEqual(captured.options.yAxis.length, 4);
assert.strictEqual(captured.options.xAxis.plotBands.length, 1);
assert.strictEqual(captured.options.chart.height, undefined);
assert.strictEqual(captured.options.navigator.enabled, true);
assert.strictEqual(captured.options.navigator.series.type, "line");
assert.strictEqual(captured.options.navigator.series.data.length, 2);
assert.strictEqual(captured.options.navigator.series.dataGrouping.enabled, false);
assert.strictEqual(captured.options.title.text, `SI.GFE · ${result.factor.alias}`);
assert.strictEqual(captured.options.series[1].name, "因子值");
const factorValueTooltip = captured.options.series[1].tooltip.pointFormatter.call({y: 0.1});
assert.ok(factorValueTooltip.startsWith("<br/>因子值:"));
assert.ok(!factorValueTooltip.includes(result.factor.alias));
captured.options.series.forEach(item => {
  assert.strictEqual(item.dataGrouping.enabled, false);
});
assert.strictEqual(typeof capturedDisplayOptions.rangeOptions, "function");
const rangedOptions = capturedDisplayOptions.rangeOptions({
  data: [{
    timestamp: "2025-01-02T15:00:00+08:00",
    open: 10, high: 12, low: 9, close: 11, volume: 100,
  }],
  __ftRange: {
    minimum: Date.parse("2025-01-02T00:00:00+08:00"),
    maximum: Date.parse("2025-01-02T23:59:59+08:00"),
  },
});
assert.strictEqual(rangedOptions.series[0].data.length, 1);
assert.strictEqual(rangedOptions.series[1].data.length, 1);
assert.strictEqual(typeof captured.options.xAxis.labels.formatter, "function");
const factorTooltip = captured.options.series[0].tooltip.pointFormatter.call({
  open: 10, high: 12, low: 9, close: 11,
});
assert.ok(factorTooltip.includes("开盘价"));
assert.ok(factorTooltip.includes("收盘价"));
assert.strictEqual(context.FTFactorSeriesResults.supports({
  jobKind: "factor_evaluation",
}), true);
assert.strictEqual(context.FTFactorSeriesResults.supports({jobKind: "ic"}), false);
assert.strictEqual(context.FTFactorSeriesResults.supportsPriceAdjustment({
  supports_term_structure: true,
}), true);
assert.strictEqual(context.FTFactorSeriesResults.supportsPriceAdjustment({
  supports_term_structure: false,
}), false);
assert.strictEqual(context.FTFactorSeriesResults.supportsPriceAdjustment({
  contracts: [{contract: "SI2501"}],
}), false);
assert.strictEqual(context.FTFactorSeriesResults.artifactOf([
  {name: "result", state: "superseded"}, {name: "result", state: "active"},
]).state, "active");
target._ftChart = chart;
context.FTFactorSeriesChart.dispose(target);
assert.strictEqual(target.__ftFactorSeriesChart, null);
assert.strictEqual(target._ftChart, null,
  "disposing a factor chart clears the shared Highcharts mount reference");
assert.strictEqual(chart.destroyed, true);
console.log("ok");
