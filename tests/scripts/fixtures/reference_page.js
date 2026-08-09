const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "scripts/worktree_manager_web/research/reference.js", "utf8",
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
  page.pathFor("run", "run:run-123"),
  "/api/runs/run-123",
);
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
