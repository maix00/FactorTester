const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "backtest-result-model.js",
});
vm.runInThisContext(fs.readFileSync(process.argv[3], "utf8"), {
  filename: "backtest-runtime-model.js",
});

const payloads = {
  equity_curve_data: {
    artifact_kind: "equity_curve",
    series: [
      {label: "A1", currency: "CNY", timestamps: [1, 2], values: [100, 110]},
      {label: "A2", currency: "CNY", timestamps: [1, 2], values: [100, 90]},
    ],
  },
  returns_over_time_data: {
    artifact_kind: "returns_over_time",
    series: [{label: "A1", timestamps: [1, 2], values: [0, 0.1]}],
  },
  metrics_over_time_data: {rows: [
    {series: "A1", timestamp: 1, cumulative_return: 0, max_drawdown: 0},
    {series: "A1", timestamp: 2, cumulative_return: 0.1, annual_return: 0.2,
      sharpe_ratio: 1.4, max_drawdown: -0.05},
  ]},
  fee_detail_data: {rows: [
    {strategy: "A1", product: "CU.SHF", fee: 2},
    {strategy: "A2", product: "AL.SHF", fee: 3},
  ]},
  margin_detail_data: {rows: [{strategy: "A1", margin: 20}]},
  ratio_detail_data: {rows: [{series: "__aggregate__", fee_total: 5}]},
};

assert.equal(
  window.FTBacktestResultModel.payloadNames.includes("group_equity_data"), false,
  "the direct result tab must not introduce a generated chart artifact",
);

const model = window.FTBacktestResultModel.build(payloads);
assert.deepEqual(model.groups, ["A1", "A2"]);
assert.deepEqual(model.tabs, [
  "summary", "equity", "returns", "metrics", "fees", "margin", "ratios",
]);
assert.equal(model.summaryRows[0].total_return, 0.1);
assert.equal(model.summaryRows[0].annual_return, 0.2);
assert.equal(model.summaryRows[0].max_drawdown, -0.05);
assert.ok(Math.abs(model.summaryRows[1].total_return + 0.1) < 1e-12);
assert.deepEqual(
  window.FTBacktestResultModel.scopedRows(payloads.fee_detail_data, "A2"),
  [{strategy: "A2", product: "AL.SHF", fee: 3}],
);
assert.deepEqual(
  window.FTBacktestResultModel.scopedRows(payloads.ratio_detail_data, "A1"),
  payloads.ratio_detail_data.rows,
  "aggregate rows remain visible when a group has no scoped rows",
);

const retainedSummary = {
  initial_capital: 1000000,
  base_currency: "CNY",
  groups: [
    {key: "A1", name: "第一组", metrics_key: "A1", group_id: "group-a1",
      group_index: 0, product_path_selection_id: "night",
      timestamps: [1700000000000, 1700000060000], total_equity: [1000000, 1080000]},
    {key: "A2", name: "第二组", metrics_key: "A2", group_id: "group-a2",
      group_index: 1, product_path_selection_id: "night",
      timestamps: [1700000000000, 1700000060000], total_equity: [1000000, 980000]},
  ],
  metrics: {
    A1: {"Total Return": 8, "Annual Return": 16, "Sharpe Ratio": 1.2,
      "Max Drawdown": 4},
    A2: {"Total Return": -2, "Annual Return": -4, "Sharpe Ratio": -0.4,
      "Max Drawdown": 9},
  },
};
const retained = window.FTBacktestResultModel.build({}, retainedSummary);
assert.deepEqual(retained.groups, ["第一组", "第二组"]);
assert.deepEqual(retained.tabs, ["summary", "group_equity", "group_metrics"]);
assert.deepEqual(
  window.FTBacktestResultModel.groupEquityEntries(retainedSummary).map(item => item.label),
  ["第一组", "第二组"],
);
assert.equal(retained.summaryRows[0].initial_equity, 1000000);
assert.equal(retained.summaryRows[0].total_return, 0.08);
assert.equal(retained.summaryRows[0].max_drawdown, -0.04);
assert.equal(window.FTBacktestResultModel.bestMetricIndex(
  retained.metricMatrix, "Total Return",
), 0);
assert.equal(window.FTBacktestResultModel.bestMetricIndex(
  retained.metricMatrix, "Max Drawdown",
), 0);
assert.deepEqual(window.FTBacktestResultModel.build({}, {
  groups: [{strategy_id: "curve-only", timestamps: [1], total_equity: [100]}],
}).tabs, ["summary", "group_equity", "group_metrics"]);
const resolved = window.FTBacktestResultModel.resolveGroup(retainedSummary, "group-a2");
assert.equal(resolved.label, "第二组");
assert.deepEqual(window.FTBacktestResultModel.groupRequest(resolved, retainedSummary), {
  product_path_selection_id: "night", group_id: "group-a2", group_index: 1,
});
assert.deepEqual(window.FTBacktestResultModel.initialSnapshot(retainedSummary), {
  product_path_selection_id: "night", group_id: "group-a1", group_index: 0,
  timestamp_ms: 1700000000000,
});

const compactSummary = {
  ...retainedSummary,
  groups: retainedSummary.groups.map(({timestamps, ...group}) => group),
};
const retainedResult = {
  groups: retainedSummary.groups,
  metrics: retainedSummary.metrics,
  runtime_info_rows: [{type: "产品范围", status: "提示", detail: "排除无覆盖产品"}],
  market_rule_warning: "两个市场规则单元格使用近似值",
  setting_fallback_warning: "一个设置被执行引擎替换",
  setting_fallbacks: [{setting_key: "fee_mode", requested_value: "auto", applied_value: "fixed"}],
  silent_default_settings: [{label: "资金分配", value_label: "等权"}],
  capital_diagnostics: {
    blocked_group_count: 1,
    blocked_groups: [{
      group_name: "A1", cheapest_product_name: "尿素",
      cheapest_required_capital: 12001.2, budget_per_product: 9000.1,
    }],
  },
};
const enriched = window.FTBacktestResultModel.build({
  result: retainedResult,
}, compactSummary);
assert.equal(enriched.summary.groups[0].timestamps[0], 1700000000000);
assert.deepEqual(window.FTBacktestResultModel.initialSnapshot(enriched.summary), {
  product_path_selection_id: "night", group_id: "group-a1", group_index: 0,
  timestamp_ms: 1700000000000,
});
assert.deepEqual(window.FTBacktestRuntimeModel.rows(enriched.summary), [
  {type: "当前运行配置", status: "默认", detail: "资金分配: 等权"},
  {type: "默认值替换", status: "已使用默认值", detail: "一个设置被执行引擎替换；fee_mode: auto → fixed"},
  {type: "产品范围", status: "提示", detail: "排除无覆盖产品"},
  {type: "市场规则", status: "近似", detail: "两个市场规则单元格使用近似值"},
  {type: "资金约束", status: "诊断", detail: "未开仓组数: 1；组 A1，最便宜品种 尿素，需求约 12001，预算约 9000"},
]);

assert.deepEqual(window.FTBacktestResultModel.evaluationWindow({
  evaluation_window: {split_ms: 1704153600000, end_ms: 1704240000000},
}), {splitMs: 1704153600000, endMs: 1704240000000});
assert.deepEqual(window.FTBacktestResultModel.evaluationWindow({}, {
  analyses: [{settings: {
    evaluation_split: "2025-01-03", timezone: "Asia/Shanghai",
  }}],
}), {
  splitMs: Date.parse("2025-01-02T16:00:00Z"), endMs: null,
});
console.log("ok");
