const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
eval(fs.readFileSync(process.argv[2], "utf8"));

const manifest = {run_fields: [
  {
    key: "task_name", default: "", request_location: "body",
    placement: "run_identity", control_template: "text",
  },
  {
    key: "acting_profile_ref", default: "", request_location: "body",
    placement: "run_identity", control_template: "profile",
  },
  {
    key: "service_port", default: "", request_location: "query",
    placement: "global_settings", freeze_target: "job.server_context.port",
  },
  {key: "retention_mode", default: "summary", request_location: "body", placement: "run_options"},
  {key: "step_mode", default: false, request_location: "body", placement: "run_options"},
  {key: "output_requests", default: [], request_location: "body", placement: "outputs"},
  {
    key: "performance_profile", default: false, request_location: "body",
    placement: "advanced_run_options",
    enabled_payload: {kind: "cumulative_flow", min_total_ms: 1000},
  },
]};

const state = {
  manifest,
  outputRequests: ["ic_series", "ic_statistics"],
  runValues: FTTestRunFields.initialValues(manifest),
};
assert.deepEqual(state.runValues, {
  task_name: "", acting_profile_ref: "", service_port: "",
  retention_mode: "summary", step_mode: false,
  performance_profile: false,
});
assert.deepEqual(FTTestRunFields.requestBody(state), {
  task_name: "",
  acting_profile_ref: "",
  retention_mode: "summary",
  step_mode: false,
  output_requests: ["ic_series", "ic_statistics"],
});

state.runValues.retention_mode = "full";
state.runValues.performance_profile = true;
assert.deepEqual(FTTestRunFields.requestBody(state), {
  task_name: "",
  acting_profile_ref: "",
  retention_mode: "full",
  step_mode: false,
  output_requests: ["ic_series", "ic_statistics"],
  performance_profile: {kind: "cumulative_flow", min_total_ms: 1000},
});
assert.equal(
  FTTestRunFields.field(manifest, "service_port").freeze_target,
  "job.server_context.port",
);
assert.deepEqual(
  FTTestRunFields.forPlacement(manifest, "run_options").map(item => item.key),
  ["retention_mode", "step_mode"],
);
console.log("ok");
