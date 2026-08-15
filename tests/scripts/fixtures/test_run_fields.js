const assert = require("node:assert/strict");
const fs = require("node:fs");

global.window = globalThis;
eval(fs.readFileSync(process.argv[2], "utf8"));

const manifest = {run_fields: [
  {
    key: "task_name", default: "", request_location: "body",
    placement: "run_identity", value_descriptor: {editor: "text"},
  },
  {
    key: "acting_profile_ref", default: "", request_location: "body",
    placement: "run_identity", value_descriptor: {editor: "profile"},
  },
  {
    key: "service_port", default: "", request_location: "query",
    placement: "global_settings", freeze_target: "job.server_context.port",
    value_descriptor: {editor: "service_port"},
  },
  {key: "retention_mode", default: "summary", request_location: "body", placement: "run_options", value_descriptor: {editor: "select"}},
  {key: "step_mode", default: false, request_location: "body", placement: "run_options", value_descriptor: {editor: "boolean"}},
  {key: "output_requests", default: [], request_location: "body", placement: "outputs", value_descriptor: {editor: "artifact_output_picker"}},
  {
    key: "performance_profile", default: false, request_location: "body",
    placement: "advanced_run_options", value_descriptor: {editor: "boolean"},
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
