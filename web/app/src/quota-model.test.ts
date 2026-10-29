import assert from "node:assert/strict";
import test from "node:test";
import { aggregateQuota, cleanupPlan, isOfflineFailure } from "./quota-model.ts";

test("combines distinct servers and latest profile observations without counting snapshots twice", () => {
  const rows = aggregateQuota([
    { id: "local", snapshot: false, data: { business_groups: [{ quota_group: "output:data", bytes: 30, job_count: 2 }] } },
    { id: "remote", snapshot: true, observedAt: "2026-01-01", data: { output_bytes: 20, output_count: 1, input_bytes: 5, input_count: 1, business_groups: [{ quota_group: "output:data", bytes: 20, job_count: 1 }] } },
  ], { protected_metadata: { factors: { bytes: 3, item_count: 1 } }, profile_snapshots: [{ storage_server_id: "remote", inventory: { observed_at: 100, categories: { research_reports: { bytes: 4, file_count: 1 } } } }], cross_server: { servers: [{ storage_server_id: "remote", status: "current", inventory: { observed_at: 200, categories: { research_reports: { bytes: 6, file_count: 2 } } } }] } }, [{ server_id: "remote", status: "pending", credit_bytes: 20 }]);
  assert.equal(rows.reduce((sum, row) => sum + row.bytes, 0), 64);
  assert.equal(rows.reduce((sum, row) => sum + row.billedBytes, 0), 44);
  assert.deepEqual(rows.find(row => row.group === "output:historical")?.lastObserved, ["2026-01-01"]);
  assert.equal(rows.find(row => row.group === "profile:research_reports")?.bytes, 6);
});

test("cancelled commands restore billing and credits never deduct protected inputs", () => {
  const server = { id: "a", snapshot: false, data: { business_groups: [{ quota_group: "input:factor", bytes: 4 }, { quota_group: "output:data", bytes: 10 }] } };
  assert.equal(aggregateQuota([server], null, [{ server_id: "a", status: "cancelled", credit_bytes: 10 }]).reduce((sum, row) => sum + row.billedBytes, 0), 14);
  const pending = aggregateQuota([server], null, [{ server_id: "a", status: "pending", credit_bytes: 50 }]);
  assert.equal(pending.find(row => row.group === "input:factor")?.billedBytes, 4);
  assert.equal(pending.find(row => row.group === "output:data")?.billedBytes, 0);
});

test("preserves unclassified artifact bytes that are absent from business groups", () => {
  const rows = aggregateQuota([{ id: "a", snapshot: false, data: { output_artifact_bytes: 15, input_artifact_bytes: 7, business_groups: [{ quota_group: "output:data", bytes: 10 }, { quota_group: "input:factor", bytes: 2 }] } }], null, []);
  assert.equal(rows.reduce((sum, row) => sum + row.billedBytes, 0), 22);
  assert.equal(rows.find(row => row.group === "output:historical")?.bytes, 5);
  assert.equal(rows.find(row => row.group === "input:other")?.bytes, 5);
});

test("cleanup targets require an intact preview or observed offline inventory", () => {
  const live = { id: "live", snapshot: false, data: { cleanup_preview: { artifact_count: 2, bytes: 7, token: "v1" }, cleanup_business_groups: [{ group: "output:data", artifact_count: 1, bytes: 3, token: "v2" }] } };
  const offline = { id: "offline", snapshot: true, observedAt: "2026-01-01", data: { output_bytes: 10, output_count: 2 } };
  const noToken = { id: "invalid", snapshot: false, data: { cleanup_preview: { artifact_count: 5, bytes: 8 } } };
  assert.deepEqual(cleanupPlan([live, offline, noToken], []).count, 4);
  assert.equal(cleanupPlan([live, offline], [], "output:data").bytes, 3);
  assert.equal(cleanupPlan([live, offline], [{ server_id: "offline", status: "pending" }]).offline.length, 0);
  assert.equal(cleanupPlan([{ ...offline, observedAt: undefined }], []).offline.length, 0);
  assert.equal(cleanupPlan([{ ...offline, queueAllowed: false }], []).offline.length, 0);
});

test("ordinary errors and authorization failures cannot schedule offline cleanup", () => {
  assert.equal(isOfflineFailure(new TypeError("network")), true);
  assert.equal(isOfflineFailure({ status: 503 }), true);
  assert.equal(isOfflineFailure({ status: 403 }), false);
  assert.equal(isOfflineFailure({ status: 500 }), false);
  assert.equal(isOfflineFailure(new Error("invalid response")), false);
});
