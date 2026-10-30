export type ReportExportFormat = "md" | "pdf";
export type ReportExportTarget = {
  publication_id?: string; source_ref?: string; source_kind?: string; owner_ref?: string;
  profile_ref?: string; profile_id?: string; report_workspace_id?: string; branch_id?: string; title?: string;
};

/** Use the selected branch's canonical channel; never infer a different user's report. */
export function reportExportURL(target: ReportExportTarget, format: ReportExportFormat): string | null {
  const explicit = String(target.publication_id || target.source_ref || "").trim();
  let channel: "client" | "server" | "public";
  let ref: string;
  if (explicit.startsWith("local:")) { channel = "client"; ref = explicit.slice(6); }
  else if (explicit.startsWith("server:")) { channel = "server"; ref = explicit.slice(7); }
  else if (explicit) {
    channel = target.source_kind === "publication" ? "public" : target.source_kind === "client" ? "client" : target.source_kind === "server_agent" || explicit.includes(":") ? "server" : "public";
    ref = explicit;
  } else {
    const parts = [target.profile_ref || target.profile_id, target.report_workspace_id, target.branch_id].map(value => String(value || "").trim());
    if (!parts.every(Boolean)) return null;
    channel = "server"; ref = parts.join(":");
  }
  if (!ref) return null;
  const prefix = channel === "client" ? "/api/client/research" : channel === "server" ? "/api/server-research" : "/api/public-research";
  const query = new URLSearchParams({ format });
  if (channel === "server" && target.owner_ref?.trim()) query.set("target_ref", target.owner_ref.trim());
  return `${prefix}/${encodeURIComponent(ref)}/export?${query}`;
}

export function reportExportPayload(target: ReportExportTarget, format: ReportExportFormat): Record<string, string> {
  return { publication_id: String(target.publication_id || "").trim(), profile_ref: String(target.profile_ref || target.profile_id || "").trim(), report_workspace_id: String(target.report_workspace_id || "").trim(), branch_id: String(target.branch_id || "").trim(), owner_ref: String(target.owner_ref || "").trim(), format: format === "md" ? "markdown" : "pdf", title: String(target.title || "") };
}

export function reportExportName(title: unknown, format: ReportExportFormat): string {
  const name = String(title || "").replace(/[\/\\:\u0000-\u001f]/g, "-").trim() || "report";
  return `${name}.${format}`;
}
