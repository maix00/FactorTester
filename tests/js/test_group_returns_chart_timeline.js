const { assert, resetGroupTest, load } = require('./group_test_harness');

const GT = resetGroupTest();
const container = document.registerElement('group_chart_container');

let captured = null;
global.Highcharts = {
  stockChart: (el, options) => {
    captured = { el, options };
    return { xAxis: [{ toValue: (value) => value }] };
  },
  dateFormat: (_fmt, ts) => String(ts),
};

load('results/charts/group_returns.js');

const jan1Close = Date.parse('2026-01-01T15:00:00+08:00');
const jan1CloseNextMinute = Date.parse('2026-01-01T15:01:00+08:00');
const jan2Open = Date.parse('2026-01-02T09:00:00+08:00');

GT.results.chart.groups.draw([
  {
    key: 'A1',
    // Internal +ns event ordering is serialized to the same millisecond for
    // charting.  The visible curve should show one bar point, with the latest
    // state at that bar, not a separate timestamp outside the bar.
    timestamps: [jan1Close, jan1Close, jan1CloseNextMinute, jan2Open],
    total_equity: [99, 100, 101, 102],
  },
]);

assert.strictEqual(container.style.display, 'block');
assert.ok(captured, 'Highcharts.stockChart was called');
assert.strictEqual(captured.options.xAxis.type, 'datetime');
assert.strictEqual(captured.options.xAxis.ordinal, true);
assert.deepStrictEqual(
  captured.options.series[0].data.map((point) => point[0]),
  [jan1Close, jan1CloseNextMinute, jan2Open],
);
assert.strictEqual(captured.options.series[0].data.length, 3);
assert.deepStrictEqual(
  captured.options.series[0].data.map((point) => point[1]),
  [100, 101, 102],
);

console.log('PASS: group returns chart keeps only actual bar timestamps');
