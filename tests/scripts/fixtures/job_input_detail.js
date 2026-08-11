const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), {
  filename: "input-detail.js",
});

const detail = window.FTJobInputDetail;
assert.equal(
  detail.artifactPath("job one", "factor/source", "?port=8141", true),
  "/api/jobs/job%20one/artifacts/factor%2Fsource/preview?port=8141",
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
console.log("ok");
