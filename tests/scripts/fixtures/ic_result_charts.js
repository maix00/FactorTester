const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
for (const file of process.argv.slice(2)) {
  vm.runInThisContext(fs.readFileSync(file, "utf8"), {filename: file});
}
const context = {t: value => value};
const factor = {
  factorAlias: "ROC", factorRef: "factor:v1:roc",
  series: [{horizon: "MIN1", delay: 0, dates: ["2024-01-02", "2024-01-03", "2024-01-04"], values: [0.1, 0.2, -0.1]}],
  statistics: [
    {forward_return_horizon: "MIN1", mean_ic: 0.08, icir_signal: 0.7},
    {forward_return_horizon: "DAY1", mean_ic: 0.03, icir_signal: 0.2},
  ],
};
const series = window.FTICResultCharts.seriesOptions(factor, context);
assert.equal(series.time.useUTC, false);
assert.equal(series.navigator.enabled, true);
assert.equal(series.series[0].data.length, 3);
assert.ok(Number.isFinite(series.series[0].data[0][0]));
const decay = window.FTICResultCharts.decayOptions(factor, context);
assert.deepEqual(decay.xAxis.categories, ["MIN1 · d0", "DAY1 · d0"]);
assert.deepEqual(decay.series[0].data, [0.08, 0.03]);
const acf = window.FTICResultCharts.autocorrelationOptions(factor, context);
assert.equal(acf.yAxis.plotLines[0].value, 0.5);
const histogram = window.FTICResultCharts.histogramOptions(factor, context);
assert.equal(histogram.series[0].data.reduce((sum, value) => sum + value, 0), 3);
const rolling = window.FTICResultCharts.rollingOptions([
  {forward_return_horizon: "MIN1", window_key: "signals:K=60", rolling_mean_ic_p50: 0.1},
], context);
assert.equal(rolling.series[0].name, "Rolling IC Mean p50");
console.log("ok");
