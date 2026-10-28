import assert from "node:assert/strict";
import test from "node:test";
import { partitionJobArtifacts, jobURL, jobDetailOf, runSpecURL, progressPercent, terminalStatus } from "./job-model.ts";
test("job reads retain execution route identity and never invent progress", () => {
  const url = jobURL({ job_id: "a/b", server_id: "remote", service_port: 8000 }, "/stream");
  assert.equal(url, "/api/jobs/a%2Fb/stream?server_id=remote&port=8000");
  assert.equal(progressPercent(null, "running"), undefined);
  assert.equal(progressPercent({ percent: 64 }), 64);
  assert.equal(progressPercent({ completed: 1, total: 4 }), 25);
  assert.equal(progressPercent(null, "succeeded"), 100);
  assert.equal(terminalStatus("paused"), false);
});

test("Manager job envelope uses canonical inner Job fields without losing task metadata", () => {
 const actual=jobDetailOf({task_detail:{job:{job_id:"j",status:"succeeded",run_spec_hash:"frozen"},progress:{phase:"complete"},result_summary:{count:0}},status:"running"});
 assert.equal(actual.status,"succeeded");assert.equal(actual.run_spec_hash,"frozen");assert.deepEqual(actual.result_summary,{count:0});assert.equal(actual.progress.phase,"complete");
});

test("RunSpec reads use the manager frozen reference and retain server scope", () => {
 const hash="a".repeat(64);assert.equal(runSpecURL("sha256:"+hash,"remote"),`/api/run-specs/${hash}?server_id=remote`);assert.throws(() => runSpecURL("../../configuration"));
});

test("retained inputs and outputs stay distinct across Manager manifests", () => {
 const rows=[{name:"source.py",role:"input"},{name:"spec.json",artifact_role:"input"},{name:"legacy.py"},{name:"tearsheet.html"},{name:"deleted.csv",state:"deleted"}];
 const actual=partitionJobArtifacts(rows,[{name:"legacy.py"}]);
 assert.deepEqual(actual.inputs.map(item=>item.name),["source.py","spec.json","legacy.py"]);
 assert.deepEqual(actual.outputs.map(item=>item.name),["tearsheet.html"]);
 assert.equal(actual.inputs[0],rows[0]);
});
