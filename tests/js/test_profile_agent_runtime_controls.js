const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync(
    path.resolve(
      __dirname,
      "../../server/manager/web/profile/agent-runtime-controls.js",
    ),
    "utf8",
  ),
  {filename: "agent-runtime-controls.js"},
);

const runtime = window.FTProfileAgentRuntimeControls;
assert.deepEqual(runtime.contextUsage({
  last_tokens: 12000,
  total_tokens: 45000,
  model_context_window: 200000,
}), {
  used: 12000,
  total: 45000,
  capacity: 200000,
  percent: 6,
});
assert.deepEqual(runtime.runtimeEventPatch({
  method: "thread/tokenUsage/updated",
  params: {
    tokenUsage: {
      modelContextWindow: 200000,
      last: {totalTokens: 12000},
      total: {totalTokens: 45000},
    },
  },
}), {
  model_context_window: 200000,
  last_tokens: 12000,
  total_tokens: 45000,
});
assert.deepEqual(runtime.runtimeEventPatch({
  method: "model/rerouted",
  params: {toModel: "safe-model"},
}), {actual_model: "safe-model"});
assert.deepEqual(runtime.runtimeEventPatch({
  method: "thread/compacted",
}, {compaction_count: 2}), {compaction_count: 3});

console.log("PASS: Profile Agent runtime metadata projection");
