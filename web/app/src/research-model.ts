export type ResearchRecord = {
  research_id?: string;
  report_id?: string;
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
  return String(row.report_id || row.publication_id || "");
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
