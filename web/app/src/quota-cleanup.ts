import type { CleanupPlan } from "./quota-model.ts";

type Request = (url: string, options?: RequestInit) => Promise<any>;
export type CleanupResult = { deleted: number; queued: number; failures: { server: string; reason: string }[] };

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
