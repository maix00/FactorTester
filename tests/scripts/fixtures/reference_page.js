const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/research/reference.js", "utf8",
), {filename: "reference.js"});

const page = window.FTReferencePage;
assert.equal(
  page.pathFor("evidence", "evidence:data_contract:sha256:abc"),
  "/api/research-evidence/evidence%3Adata_contract%3Asha256%3Aabc",
);
assert.equal(
  page.pathFor("trial_plan", "trial-plan:sha256:abc"),
  "/api/trial-plans/direct/abc",
);
assert.equal(
  page.pathFor("run_spec", "runspec:sha256:abc"),
  "/api/run-specs/abc",
);
assert.equal(
  page.pathFor("run_spec", "run-spec:sha256:def"),
  "/api/run-specs/def",
);
assert.equal(
  page.pathFor("run_spec", "run_spec:sha256:ghi"),
  "/api/run-specs/ghi",
);
assert.equal(
  page.pathFor("run_spec", "runspec:sha256:abc", "public-1"),
  "/api/run-specs/abc?server_id=public-1",
);
assert.equal(
  page.pathFor("run", "run:run-123"),
  "/api/runs/run-123",
);
assert.equal(
  page.routeFor("run_spec", "runspec:sha256:abc", "运行配置"),
  "/reference?kind=run-spec&target=runspec%3Asha256%3Aabc&label=%E8%BF%90%E8%A1%8C%E9%85%8D%E7%BD%AE",
);
assert.equal(
  page.routeFor("run_spec", "runspec:sha256:abc", "运行配置", "public-1"),
  "/reference?kind=run-spec&target=runspec%3Asha256%3Aabc&label=%E8%BF%90%E8%A1%8C%E9%85%8D%E7%BD%AE&server_id=public-1",
);
assert.equal(
  page.jobRouteFor({job_id: "job:abc", service_port: 8000, server_id: "remote-main"}),
  "/jobs/8000/abc?server_id=remote-main",
);
assert.equal(
  page.jobRouteFor({job_id: "abc", server_id: "remote-main"}),
  "/jobs/abc?server_id=remote-main",
);
assert.equal(
  page.resourceEndpoint({detailFields: [
    {name: "publication_id", value: "local:record:branch"},
    {name: "resource_id", value: "a".repeat(24)},
  ]}),
  "/api/client/research/record%3Abranch/local-resources/aaaaaaaaaaaaaaaaaaaaaaaa?inline=1",
);
assert.equal(
  page.resourceEndpoint({detailFields: [
    {name: "publication_id", value: "publication-123"},
    {name: "resource_id", value: "b".repeat(24)},
  ]}),
  "/api/public-research/publication-123/local-resources/bbbbbbbbbbbbbbbbbbbbbbbb?inline=1",
);
assert.equal(page.resourceEndpoint({detailFields: []}), null);
assert.equal(page.pathFor("obligation", "obligation:one"), "");
assert.deepEqual(page.presentationFor("factor-family"), {
  title: "因子家族", symbol: "function", tone: "factor",
});
assert.deepEqual(page.presentationFor("factor_set"), {
  title: "因子集合", symbol: "square.stack.3d.up", tone: "factor",
});
assert.deepEqual(page.presentationFor("evidence"), {
  title: "证据", symbol: "doc.text.magnifyingglass", tone: "evidence",
});
console.log("ok");
