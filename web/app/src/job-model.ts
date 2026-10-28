export type JobReference = { job_id: string; server_id?: string; service_port?: number; task_name?: string; status?: string; execution_node_id?: string };
export function jobURL(job: JobReference, suffix = ""): string {
  const params = new URLSearchParams();
  if (job.server_id) params.set("server_id", job.server_id);
  if (job.execution_node_id) params.set("node_execution", "1");
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
/** Current Manager envelope: routing metadata and task_detail.job stay distinct. */
export function jobDetailOf(payload: Record<string, any>): Record<string, any> {
  const task = payload.task_detail || payload;
  return { ...task, ...(task.job || {}),
    progress: task.progress ?? task.job?.progress,
    run_spec_hash: task.job?.run_spec_hash ?? task.run_spec_hash,
  };
}
export function runSpecURL(hash: string, serverID?: string): string {
 const value=hash.replace(/^sha256:/i, "");
 if(!/^[a-f0-9]{64}$/i.test(value))throw new Error("Invalid RunSpec hash");
 const params=new URLSearchParams();if(serverID)params.set("server_id",serverID);
 return `/api/run-specs/${encodeURIComponent(value)}${params.size ? `?${params}` : ""}`;
}
