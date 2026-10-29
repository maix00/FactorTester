import type { CleanupPlan } from "./quota-model.ts";

type Request = (url: string, options?: RequestInit) => Promise<any>;
export type CleanupResult = { deleted: number; queued: number; failures: { server: string; reason: string }[] };

/** Retrieve a fresh job-specific preview before deleting one job's outputs. */
export async function jobCleanupPreview(serverId: string, jobId: string, request: Request): Promise<any> {
  if (!serverId || !jobId) throw new Error("Missing server or job identity");
  const previewQuery = new URLSearchParams({ server_id: serverId, job_id: jobId });
  const data = await request(`/api/jobs/storage?${previewQuery}`);
  if (data.storage_server_id !== serverId) throw new Error("Storage server identity mismatch");
  const preview = data.job_cleanup_preview;
  if (!preview || !Number.isInteger(preview.artifact_count) || preview.artifact_count <= 0 || !Number.isInteger(preview.bytes) || preview.bytes < 0 || typeof preview.token !== "string" || !preview.token) throw new Error("Missing job cleanup preview");
  return preview;
}
export async function deleteJobOutputs(serverId: string, jobId: string, preview: any, request: Request): Promise<any> {
  if (!serverId || !jobId || !preview || !Number.isInteger(preview.artifact_count) || preview.artifact_count <= 0 || !Number.isInteger(preview.bytes) || preview.bytes < 0 || typeof preview.token !== "string" || !preview.token) throw new Error("Invalid job cleanup preview");
  const query = new URLSearchParams({ cleanup: "eligible", server_id: serverId, job_id: jobId, expected_count: String(preview.artifact_count), expected_bytes: String(preview.bytes), expected_token: preview.token });
  return request(`/api/jobs/artifacts?${query}`, { method: "DELETE" });
}

/** Send each server its own frozen preview. A failed server never prevents later targets. */
export async function executeCleanup(plan: CleanupPlan, group: string, request: Request): Promise<CleanupResult> {
  const result: CleanupResult = { deleted: 0, queued: 0, failures: [] };
  for (const { server, preview } of plan.live) {
    const query = new URLSearchParams({ cleanup: "eligible", server_id: server.id, expected_count: String(preview.artifact_count), expected_bytes: String(preview.bytes), expected_token: preview.token });
    if (group) query.set("group", group);
    try {
      const response = await request(`/api/jobs/artifacts?${query}`, { method: "DELETE" });
      result.deleted += Number(response.deleted_artifacts || 0);
      if (response.failed_files) result.failures.push({ server: server.id, reason: `failed_files:${response.failed_files}` });
    } catch (reason) { result.failures.push({ server: server.id, reason: reason instanceof Error ? reason.message : String(reason) }); }
  }
  for (const server of plan.offline) {
    try {
      await request("/api/storage/deferred-job-cleanup", { method: "POST", body: JSON.stringify({ server_id: server.id, expected_bytes: server.data.output_bytes, expected_count: server.data.output_count, observed_at: server.observedAt }) });
      result.queued++;
    } catch (reason) { result.failures.push({ server: server.id, reason: reason instanceof Error ? reason.message : String(reason) }); }
  }
  return result;
}
