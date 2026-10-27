export type JobReference = { job_id: string; server_id?: string; service_port?: number; task_name?: string; status?: string };
export function jobURL(job: JobReference, suffix = ""): string {
  const params = new URLSearchParams();
  if (job.server_id) params.set("server_id", job.server_id);
  if (job.service_port) params.set("port", String(job.service_port));
  return `/api/jobs/${encodeURIComponent(job.job_id)}${suffix}${params.size ? `?${params}` : ""}`;
}
export const terminalStatus = (status?: string): boolean => ["succeeded", "failed", "cancelled"].includes(status || "");
export function progressPercent(progress: Record<string, unknown> | null, status?: string): number | undefined {
  if (status === "succeeded") return 100;
  if (!progress) return undefined;
  const raw = Number(progress.percent);
  if (progress.percent !== undefined && progress.percent !== null && Number.isFinite(raw)) return Math.max(0, Math.min(100, raw));
  const total = Number(progress.total), completed = Number(progress.completed);
  return total > 0 && Number.isFinite(completed) ? Math.max(0, Math.min(100, completed / total * 100)) : undefined;
}
