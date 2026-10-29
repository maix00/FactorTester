import assert from "node:assert/strict";
import test from "node:test";
import { cleanupPlan } from "./quota-model.ts";
import { deleteJobOutputs, executeCleanup, jobCleanupPreview } from "./quota-cleanup.ts";

test("per-server previews survive partial failure and offline cleanup is queued", async () => {
  const plan = cleanupPlan([
    { id: "a", snapshot: false, data: { cleanup_preview: { artifact_count: 2, bytes: 5, token: "old token" } } },
    { id: "b", snapshot: false, data: { cleanup_preview: { artifact_count: 1, bytes: 9, token: "new token" } } },
    { id: "c", snapshot: true, observedAt: "2026-01-01", data: { output_count: 3, output_bytes: 12 } },
  ], []);
  const calls: { url: string; options?: RequestInit }[] = [];
  const result = await executeCleanup(plan, "", async (url, options) => {
    calls.push({ url, options });
    if (url.includes("server_id=a")) throw new Error("preview changed");
    return url.includes("server_id=b") ? { deleted_artifacts: 1, failed_files: 1 } : { success: true };
  });
  assert.deepEqual(result, { deleted: 1, queued: 1, failures: [{ server: "a", reason: "preview changed" }, { server: "b", reason: "failed_files:1" }] });
  assert.equal(new URL(calls[1].url, "http://localhost").searchParams.get("expected_token"), "new token");
  assert.deepEqual(JSON.parse(String(calls[2].options?.body)), { server_id: "c", expected_bytes: 12, expected_count: 3, observed_at: "2026-01-01" });
});

test("single-job cleanup requires a matching server and sends a fresh scoped preview", async () => {
  const calls: string[] = [];
  const request = async (url: string): Promise<any> => { calls.push(url); return calls.length === 1 ? { storage_server_id: "a", job_cleanup_preview: { artifact_count: 2, bytes: 42, token: "v1" } } : { deleted_artifacts: 2 }; };
  const preview = await jobCleanupPreview("a", "job-1", request);
  await deleteJobOutputs("a", "job-1", preview, request);
  const query = new URL(calls[1], "http://localhost").searchParams;
  assert.equal(query.get("job_id"), "job-1");
  assert.equal(query.get("expected_token"), "v1");
  await assert.rejects(jobCleanupPreview("a", "job-1", async () => ({ storage_server_id: "b" })), /identity mismatch/);
});
