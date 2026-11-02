import assert from "node:assert/strict";
import test from "node:test";
import { frozenRunSpecSections } from "./frozen-run-spec-model.ts";

test("owner-scoped RunSpec preserves identity, configuration and every execution option", () => {
  const runSpec = {
    workspace_id: "workspace-1",
    analyses: ["backtest"],
    retention_mode: "all",
    configuration: { shared: { product_group_ref: "group:v1:one", factor_ref: "factor:v2:one" }, execution: { next_bar_open: true } },
  };
  const response = { run_spec_hash: "abc", run_spec_version: 2, configuration_id: "cfg", configuration_revision: 0,
    alias_zh: "回测", complete_parameters_json: JSON.stringify(runSpec), run_spec: runSpec };
  const before = JSON.stringify(response);
  const result = frozenRunSpecSections(response);
  assert.deepEqual(result.identity, { run_spec_hash: "abc", run_spec_version: 2, configuration_id: "cfg", configuration_revision: 0, alias_zh: "回测" });
  assert.equal(result.configuration, runSpec.configuration);
  assert.deepEqual(result.options, { workspace_id: "workspace-1", analyses: ["backtest"], retention_mode: "all" });
  assert.equal(JSON.stringify(response), before);
});

test("direct and historic configurations remain visible even without a Nautilus contract", () => {
  const configuration = { payload: { analyses: { backtest: { execution: { backend: "legacy", frequency: "MIN1" } } } } };
  const value = { configuration, custom: false, count: 0 };
  const result = frozenRunSpecSections(value, "sha256:abc");
  assert.deepEqual(result.identity, { run_spec_hash: "sha256:abc" });
  assert.equal(result.configuration, configuration);
  assert.deepEqual(result.options, { custom: false, count: 0 });
});

test("missing or null configuration and unexpected values are retained", () => {
  assert.deepEqual(frozenRunSpecSections({ configuration: null, x: 1 }), {
    identity: {}, configuration: null, hasConfiguration: true, options: { x: 1 },
  });
  assert.deepEqual(frozenRunSpecSections({ x: 1 }), {
    identity: {}, configuration: undefined, hasConfiguration: false, options: { x: 1 },
  });
  assert.deepEqual(frozenRunSpecSections([1, 2]), {
    identity: {}, configuration: undefined, hasConfiguration: false, options: [1, 2],
  });
});
