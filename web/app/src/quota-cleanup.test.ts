import assert from "node:assert/strict";
import test from "node:test";
import { cleanupPlan } from "./quota-model.ts";
import { deleteJobOutputs, executeCleanup, jobCleanupPreview } from "./quota-cleanup.ts";
import type { CleanupPlan } from "./quota-model.ts";

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

test("cross-server cleanup uses each live preview and queues only observed offline inventory", async () => {
  const plan: CleanupPlan = {
    live: [
      { server: { id: "live-a", snapshot: false, data: {} }, preview: { artifact_count: 2, bytes: 9, token: "token-a" } },
      { server: { id: "live-b", snapshot: false, data: {} }, preview: { artifact_count: 1, bytes: 4, token: "token-b" } },
    ],
    offline: [{ id: "offline-c", snapshot: true, observedAt: "2026-10-20T00:00:00Z", data: { output_count: 3, output_bytes: 12 } }],
    count: 6,
    bytes: 25,
  };
  const calls: { url: string; method: string; body?: string }[] = [];
  const request = async (url: string, options?: RequestInit): Promise<any> => {
    calls.push({ url, method: options?.method || "GET", body: options?.body as string | undefined });
    return url.startsWith("/api/jobs/artifacts") ? { deleted_artifacts: 1 } : {};
  };

  const result = await executeCleanup(plan, "", request);

  assert.deepEqual(result, { deleted: 2, queued: 1, failures: [] });
  assert.equal(calls.length, 3);
  assert.deepEqual(calls.slice(0, 2).map(({ url, method }) => {
    const query = new URLSearchParams(url.split("?")[1]);
    return [method, query.get("server_id"), query.get("expected_token")];
  }), [["DELETE", "live-a", "token-a"], ["DELETE", "live-b", "token-b"]]);
  assert.deepEqual(JSON.parse(calls[2].body || "{}"), {
    server_id: "offline-c",
    expected_bytes: 12,
    expected_count: 3,
    observed_at: "2026-10-20T00:00:00Z",
  });
});

test("one server failure does not stop cleanup requests for later servers", async () => {
  const plan: CleanupPlan = {
    live: [
      { server: { id: "failed", snapshot: false, data: {} }, preview: { artifact_count: 1, bytes: 3, token: "old" } },
      { server: { id: "healthy", snapshot: false, data: {} }, preview: { artifact_count: 1, bytes: 5, token: "fresh" } },
    ],
    offline: [],
    count: 2,
    bytes: 8,
  };
  const requested: string[] = [];
  const request = async (url: string): Promise<any> => {
    const server = new URLSearchParams(url.split("?")[1]).get("server_id") || "";
    requested.push(server);
    if (server === "failed") throw new Error("preview expired");
    return { deleted_artifacts: 1 };
  };

  const result = await executeCleanup(plan, "output:data", request);

  assert.deepEqual(requested, ["failed", "healthy"]);
  assert.deepEqual(result, { deleted: 1, queued: 0, failures: [{ server: "failed", reason: "preview expired" }] });
});
