export type SourceRow = Record<string, any>;
export const sourceIdentity = (row: SourceRow): string => String(row.family_id || row.bundle_id || row.id || row.source_name || "").trim();
export const sourceTitle = (row: SourceRow): string => String(row.family_name || row.bundle_name || row.source_name || row.id || "—");
export function sourceCapability(member: SourceRow, capabilities: SourceRow | null): {value: SourceRow | null; origin: "snapshot" | "service" | "missing"} {
  if (member.nautilus_capability && Object.keys(member.nautilus_capability).length) return {value:member.nautilus_capability,origin:"snapshot"};
  const value = capabilities?.market_data_sources?.members?.find((item: SourceRow) => String(item.member_key || "") === String(member.id || member.key || ""));
  return {value:value || null,origin:value ? "service" : "missing"};
}
export function bookTypes(capabilities: SourceRow | null): string[] {
  return (capabilities?.simulated_venue_config?.fields?.find((field: SourceRow) => field.path === "book_type")?.options || []).map((item: any) => typeof item === "object" ? item.value : item).filter(Boolean);
}
