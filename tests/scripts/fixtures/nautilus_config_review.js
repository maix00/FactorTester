const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
global.structuredClone = value => JSON.parse(JSON.stringify(value));
global.document = {createElement: tagName => ({
  tagName, children: [], className: "", textContent: "", classList: {toggle() {}},
  setAttribute() {}, append(...items) { this.children.push(...items); },
  get childElementCount() { return this.children.length; },
})};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/workbench/nautilus-configuration.js", "utf8",
), {filename: "nautilus-configuration.js"});

function state() {
  return {
    kind: "backtest", executionBackend: "nautilus_trader",
    values: {fee_mode: "zero"}, runValues: {},
    analysis: {groups: [{factor_candidate_refs: ["frozen-factor"]}]},
  };
}

function context(requests, response, capabilities) {
  return {
    servicePath: path => `${path}?port=8000`,
    api: async (path, options) => {
      requests.push({path, options});
      return path.includes("capabilities") ? capabilities : response;
    },
  };
}

window.FTTests = {
  ensureFactorsForExecution: async (_, draft) => { draft.factorLoaded = true; },
  ensureProductsForExecution: async (_, draft) => { draft.productLoaded = true; },
};
window.FTTestConfiguration = {
  configurationPayload: draft => ({
    analyses: {backtest: {execution: {backend: draft.executionBackend}}},
  }),
};
window.FTTestRunFields = {requestBody: draft => ({output_requests: draft.runValues.outputs || []})};
window.FTTestConfigurationCompiler = {executionSettings: (_, values) => values};

const accepted = {
  engine: "nautilus_trader", ready: true,
  effective_configuration: {account: {initial_balance: 100000}},
  fields: [{path: "execution.settings.fee_mode", label: "手续费", value: "zero", status: "nt_native"}],
  blockers: [],
};

(async () => {
  const draft = state();
  const requests = [];
  const capabilityResponse = {
    backtest_submission: {available: true},
    simulated_venue_config: {parameter_coverage: [{
      parameter: "fee_model", runspec_path: "venues[].native_config.fee_model",
      status: "ft_adapter", note: "RunSpec tags and constructs a Nautilus FeeModel.",
    }], execution_policy_coverage: [{
      parameter: "execution_timing", runspec_path: "execution_timing",
      native_parameters: "TimeInForce.AT_THE_OPEN",
      status: "ft_adapter", note: "冻结为下一 Bar 开盘。",
    }, {
      parameter: "daily_settlement", runspec_path: "instrument_execution_policy.daily_settlement",
      native_parameters: "InstrumentClose(DAILY_SETTLEMENT)",
      status: "unsupported", note: "结算事件适配器尚未接通。",
    }, {
      parameter: "position_cost_basis", runspec_path: "instrument_execution_policy.position_cost_basis.default",
      native_parameters: "position_cost_basis",
      status: "nt_native", note: "支持 WEIGHTED_AVERAGE、FIFO、LIFO、HIFO。",
    }]},
  };
  const result = await window.FTNautilusConfiguration.validateServer(
    context(requests, accepted, capabilityResponse), draft,
    {id: "__backtest__"},
  );
  assert.equal(result.ready, true);
  assert.equal(draft.nautilusReview.status, "ready");
  assert.equal(requests[0].path, "/api/nautilus/capabilities?port=8000");
  assert.equal(requests[1].path, "/api/nautilus/config/preview?port=8000");
  assert.equal(JSON.parse(requests[1].options.body).configuration.analyses.backtest.execution.backend,
    "nautilus_trader");
  const tree = window.FTNautilusConfiguration.render({
    t: value => value,
    button: label => ({tagName: "button", textContent: label, classList: {toggle() {}},
      setAttribute() {}, children: []}),
  }, draft, {defaults: {}}, {});
  const nodes = (node, found = []) => {
    found.push(node);
    node.children?.forEach(child => nodes(child, found));
    return found;
  };
  const all = nodes(tree);
  assert.equal(all.filter(node => node.className === "nautilus-config-review-section").length, 7);
  assert.ok(all.some(node => node.textContent === "服务端解析的完整有效配置"));
  assert.ok(all.some(node => node.textContent?.includes('"initial_balance": 100000')));
  assert.ok(all.some(node => node.textContent === "RunSpec tags and constructs a Nautilus FeeModel."));
  assert.ok(all.some(node => node.textContent === "Nautilus 执行语义参数映射到 RunSpec"));
  assert.ok(all.some(node => node.textContent === "结算事件适配器尚未接通。"));
  assert.ok(all.some(node => node.textContent === "TimeInForce.AT_THE_OPEN → execution_timing"));
  draft.values.fee_mode = "historical";
  assert.notEqual(draft.nautilusReview.fingerprint,
    window.FTNautilusConfiguration.fingerprint(draft));

  const unavailable = state();
  await assert.rejects(
    window.FTNautilusConfiguration.requireReady(
      context([], accepted, {backtest_submission: {available: false}}), unavailable,
      {id: "__backtest__"},
    ), /尚未启用/,
  );
  assert.equal(unavailable.nautilusReview.response.ready, false);

  await assert.rejects(
    window.FTNautilusConfiguration.requireReady(
      context([], {...accepted, ready: false, blockers: [
        {path: "execution.settings.liquidity_mode", reason: "容量配置未支持"},
      ]}, {backtest_submission: {available: true}}), state(), {id: "__backtest__"},
    ), /容量配置未支持/,
  );
  await assert.rejects(
    window.FTNautilusConfiguration.validateServer(
      context([], {ready: true}, {backtest_submission: {available: true}}),
      state(), {id: "__backtest__"},
    ), /未返回有效/,
  );
  console.log("ok");
})().catch(error => { console.error(error); process.exitCode = 1; });
