const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-group-equity-chart.js",
});

const chart = window.FTBacktestGroupEquityChart;
const jan1 = Date.parse("2026-01-01T15:00:00+08:00");
const jan1Next = Date.parse("2026-01-01T15:01:00+08:00");
const jan2 = Date.parse("2026-01-02T09:00:00+08:00");
const summary = {
  initial_capital: 100,
  base_currency: "CNY",
  groups: [{
    strategy_id: "strategy-a", display_name: "策略 A", is_ls: true,
    timestamps: [jan1, jan1, jan1Next, jan2],
    total_equity: [99, 100, 101, 102],
  }, {
    strategy_id: "strategy-b", display_name: "策略 B",
    timestamps: [jan1, jan2], total_equity: [100, 98],
  }],
};
const groups = chart.equityGroups(summary);
const timeline = chart.buildTimeline(groups);
const series = chart.buildSeries(groups, timeline);

assert.deepEqual(timeline, [jan1, jan1Next, jan2]);
assert.deepEqual(series[0].data, [[jan1, 100], [jan1Next, 101], [jan2, 102]]);
assert.deepEqual(series[1].data, [[jan1, 100], [jan1Next, null], [jan2, 98]]);
assert.equal(series[0].dashStyle, undefined, "is_ls must not change equity-curve styling");
assert.equal(series[0].color, undefined, "all strategies use the normal chart palette");

const context = {t: value => value};
const inSample = chart.optionsFor(summary, context, {
  splitMs: jan1Next, endMs: jan2, showOutOfSample: false,
});
assert.equal(inSample.xAxis.type, "datetime");
assert.equal(inSample.xAxis.ordinal, true);
assert.equal(inSample.xAxis.max, jan1Next);
assert.deepEqual(inSample.xAxis.plotBands, []);
assert.equal(inSample.yAxis.length, 2);
assert.equal(inSample.navigator.enabled, true);
assert.equal(inSample.scrollbar.enabled, true);
assert.equal(inSample.rangeSelector.enabled, false);
assert.equal(inSample.accessibility.enabled, false);
assert.equal(inSample.title.style.color, "#1d1d1f");
assert.equal(inSample.plotOptions.series.cursor, undefined);
assert.equal(inSample.plotOptions.series.point, undefined);

const outOfSample = chart.optionsFor(summary, context, {
  splitMs: jan1Next, endMs: jan2, showOutOfSample: true,
});
assert.equal(outOfSample.xAxis.max, null);
assert.equal(outOfSample.xAxis.plotBands[0].from, jan1Next);
assert.equal(outOfSample.xAxis.plotBands[0].to, jan2);

const snapshotTimestamps = [];
const withSnapshot = chart.optionsFor(summary, context, {
  onSnapshot: value => snapshotTimestamps.push(value),
});
assert.equal(withSnapshot.plotOptions.series.cursor, "pointer");
withSnapshot.plotOptions.series.point.events.click.call({x: jan2});
withSnapshot.chart.events.click.call({xAxis: [{value: jan1Next + 10}]}, {
  xAxis: [{value: jan1Next + 10}],
});
assert.deepEqual(snapshotTimestamps, [jan2, jan1Next]);

assert.equal(chart.nearestTimelineMs(timeline, jan1Next + 1), jan1Next);
console.log("ok");
