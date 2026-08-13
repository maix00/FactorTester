const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "input-detail.js",
});

const detail = window.FTJobInputDetail;
assert.equal(
  detail.artifactPath("job one", "factor/source", "?port=8141"),
  "/api/jobs/job%20one/artifacts/factor%2Fsource?port=8141",
);
assert.deepEqual(detail.factorConfigurations({
  configuration: {shared: {factors: [
    {
      source_kind: "transient", transient_factor_id: "UploadedMomentum",
      factor_family_alias: "UploadedMomentum", params: {N: "5d"},
    },
    {factor_family_alias: "PublicFactor", params: {N: "2d"}},
  ]}},
}, "UploadedMomentum").map(item => item.params), [{N: "5d"}]);
const dependency = detail.dependencyManifestItem({
  run_input_dependency_policy: {files: [{
    path: "strategy-configs/dynamic-hold.yaml",
    purpose: "strategy_configuration",
    analyses: ["backtest"],
  }]},
}, {
  artifact_kind: "run_dependency",
  logical_path: "strategy-configs/dynamic-hold.yaml",
});
assert.equal(dependency.purpose, "strategy_configuration");
assert.equal(detail.purposeLabel(dependency.purpose), "策略配置");
assert.equal(detail.analysisLabel(dependency.analyses[0]), "回测");
console.log("ok");
