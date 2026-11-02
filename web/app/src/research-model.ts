export type ResearchRecord = {
  research_id?: string;
  report_id?: string;
  source_ref?: string;
  publication_id?: string;
  branches?: ReportBranch[];
};

export type ReportBranch = {
  publication_id?: string;
  branch_ref?: string;
  title?: string;
  profile_ref?: string;
  source_kind?: string;
  selected?: boolean;
};

export function researchRowID(row: ResearchRecord): string {
  return String(row.research_id || "");
}

export function reportRowID(row: ResearchRecord): string {
  return String(row.report_id || row.source_ref || row.publication_id || "");
}

export function linkedResearchID(row: ResearchRecord & { research?: { research_id?: string } }): string {
  return String(row.research_id || row.research?.research_id || "");
}

export function reportBranches(row: ResearchRecord): ReportBranch[] {
  const branches = Array.isArray(row.branches) ? row.branches : [];
  const readable = branches.filter((branch) => String(branch.publication_id || "").trim());
  if (readable.length) return readable;
  const publicationID = String(row.publication_id || "").trim();
  return publicationID ? [{ publication_id: publicationID, source_kind: "publication" }] : [];
}

export function selectReportBranch(
  row: ResearchRecord,
  publicationID = "",
): ReportBranch | undefined {
  const branches = reportBranches(row);
  return branches.find((branch) => branch.publication_id === publicationID)
    || branches.find((branch) => branch.selected)
    || branches[0];
}

/** Only offer addressable profiles and avoid recreating an existing relation. */
export function researchRelationCandidates(kind: "profile" | "workspace" | "report", rows: Record<string, any>[], existing: Record<string, any>, owner: string): Record<string, any>[] {
  const bound = new Set((existing.members || []).map((row: Record<string, any>) => JSON.stringify([
    String(row.principal_ref || row.owner_ref || owner || ""), String(row.profile_ref || "").replace(/^profile:/, ""),
  ])));
  const workspaces = new Set((existing.workspaces || []).filter((row: Record<string, any>) => String(row.status || "active") === "active").map((row: Record<string, any>) => JSON.stringify([row.principal_ref, row.profile_ref])));
  return rows.filter(row => {
    const profile = String(row.profile_ref || row.profile_id || "");
    const principal = String(row.principal_ref || row.owner_ref || owner || "");
    if (!profile || !principal) return false;
    return kind === "profile" ? !bound.has(JSON.stringify([principal, profile.replace(/^profile:/, "")])) : String(row.status || "active") === "active" && (kind !== "workspace" || !workspaces.has(JSON.stringify([principal, profile])));
  });
}


type DirectoryRow = Record<string, any>;

/** A Profile copy is a distinct directory row, not a distinct human user. */
export function researchDirectoryRowKey(row: DirectoryRow, reports = false): string {
  return JSON.stringify([row.__local ? "local" : "server", String(row.owner_ref || row.owner || ""),
    String(row.profile_ref || row.profile_id || row.selected_branch?.profile_ref || ""),
    researchRowID(row), reports ? reportRowID(row) : ""]);
}

/** Merge a Manager projection with every matching local Profile copy in O(n).
 * Neither matching nor grouping authorizes access; inputs are already scoped.
 */
export function mergeResearchDirectory(server: DirectoryRow[], local: DirectoryRow[], principal: string): DirectoryRow[] {
  const remaining = new Map<string, DirectoryRow>();
  const copies = new Map<string, DirectoryRow[]>();
  for (const row of local) {
    const key = researchDirectoryRowKey(row);
    if (remaining.has(key)) continue;
    remaining.set(key, row);
    if (String(row.owner_ref || row.owner || "") !== principal) continue;
    const id = researchRowID(row);
    const group = copies.get(id);
    if (group) group.push(row); else copies.set(id, [row]);
  }
  const merged: DirectoryRow[] = [];
  for (const row of server) {
    const candidates = String(row.owner_ref || row.owner || "") === principal ? copies.get(researchRowID(row)) : undefined;
    const profile = String(row.profile_ref || row.profile_id || "");
    const matching = candidates?.filter(copy => !profile || profile === String(copy.profile_ref || copy.profile_id || ""));
    if (!matching?.length) { merged.push(row); continue; }
    for (const copy of matching) {
      remaining.delete(researchDirectoryRowKey(copy));
      merged.push({...row, __hasLocal:true, profile_id:copy.profile_id, profile_ref:copy.profile_ref || copy.profile_id});
    }
  }
  return [...remaining.values(), ...merged];
}
