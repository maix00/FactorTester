import assert from "node:assert/strict";
import test from "node:test";
import { jobURL, progressPercent, terminalStatus } from "./job-model.ts";
test("job reads retain execution route identity and never invent progress", () => {
  const url = jobURL({ job_id: "a/b", server_id: "remote", service_port: 8000 }, "/stream");
  assert.equal(url, "/api/jobs/a%2Fb/stream?server_id=remote&port=8000");
  assert.equal(progressPercent(null, "running"), undefined);
  assert.equal(progressPercent({ percent: 64 }), 64);
  assert.equal(progressPercent({ completed: 1, total: 4 }), 25);
  assert.equal(progressPercent(null, "succeeded"), 100);
  assert.equal(terminalStatus("paused"), false);
});
