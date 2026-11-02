import { request } from "./configuration/api.ts";

/** Download from the authorized origin using a short-lived object capability. */
export async function evidenceFile(evidenceRef: string, sourceRef: string): Promise<{ blob: Blob; filename: string }> {
  const issued = await request("/api/transfers/objects/download-access", {
    method: "POST", body: JSON.stringify({object_kind:"evidence_file", evidence_ref:evidenceRef, source_ref:sourceRef}),
  });
  const access = issued.access || {};
  if (typeof access.url !== "string" || !access.url || typeof access.bearer !== "string" || !access.bearer) throw new Error("invalid_transfer_access");
  const response = await fetch(access.url, {credentials:"omit", redirect:"error", headers:{Authorization:`Bearer ${access.bearer}`}});
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(typeof result.error === "string" && result.error || `HTTP ${response.status}`);
  }
  const blob = await response.blob();
  const size = Number(access.expected_size ?? issued.object?.size_bytes ?? 0);
  if (Number.isFinite(size) && size > 0 && blob.size !== size) throw new Error("evidence_size_mismatch");
  return {blob, filename:String(issued.object?.filename || "")};
}
