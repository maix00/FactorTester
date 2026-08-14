const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {
  FTBacktestAnalysisUI: {
    finite(value) {
      const number = Number(value);
      return value == null || value === "" || !Number.isFinite(number) ? null : number;
    },
  },
};
process.argv.slice(2).forEach(modulePath => vm.runInThisContext(
  fs.readFileSync(modulePath, "utf8"), {filename: modulePath},
));

const parts = Object.assign(
  {}, window.FTBacktestGroupDetailParts, window.FTBacktestGroupDetailProducts,
);
const windowSummary = parts.summarizeIntradayWindow([
  {time: "09:01", count: 2, sum: 0.01},
  {time: "09:02", count: 3, sum: -0.005},
  {time: "10:00", count: 4, sum: 0.02},
], "09:01", "09:02");
assert.equal(windowSummary.label, "09:01-09:02");
assert.equal(windowSummary.count, 5);
assert.equal(windowSummary.sum, 0.005);
assert.ok(Math.abs(windowSummary.share_of_total_sum - 0.2) < 1e-12);

const covered = {
  mean_active_contribution: 0.0005,
  product: {fee: {open: 0.0001, close_today: 0.0002}},
};
assert.ok(Math.abs(parts.roundTripFee(covered) - 0.0003) < 1e-12);
assert.equal(parts.feeCoverageClass(covered), "backtest-fee-covered");
assert.equal(parts.feeCoverageClass({
  ...covered, mean_active_contribution: 0.0002,
}), "");
assert.equal(parts.productDescription({name: "SI.GFE", desc: "工业硅"}), "工业硅");
assert.equal(parts.productDescription({name: "SI.GFE", desc: "SI.GFE"}), "—");
console.log("ok");
