import { request } from "./configuration/api.ts";
import { jobURL, type JobReference } from "./job-model.ts";
/** Manager issues a scoped grant; bytes come from its existing data plane. */
export async function readJobArtifact(job: JobReference, name: string, signal: AbortSignal): Promise<Blob> {
  const issued = await request(jobURL(job, `/artifacts/${encodeURIComponent(name)}/access`), { method: "POST", headers: { "Idempotency-Key": `artifact-read:${crypto.randomUUID()}` }, signal });
  const access = issued.access;
  if (!access?.url || !access.bearer) throw new Error("Invalid artifact access grant");
  const response = await fetch(access.url, { credentials: "omit", redirect: "error", headers: { Authorization: `Bearer ${access.bearer}` }, signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.blob();
}
