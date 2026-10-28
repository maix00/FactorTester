/** Match the same product fields that the directory shows, without changing server pagination. */
export function catalogSearchMatches(query: string, displayed: string[], extra: unknown[] = []): boolean {
  const needle = query.trim().toLocaleLowerCase();
  return !needle || [...displayed, ...extra].some(value =>
    typeof value === "string" && value.toLocaleLowerCase().includes(needle));
}

/** Select the registered resource, never an unrelated array in the same response. */
export function catalogRows(payload: Record<string, unknown>, domain: string, tab: string): Record<string, unknown>[] {
  const key = domain === "strategies" ? tab === "strategyFamilies" ? "families" : "items"
    : domain === "factors" ? tab === "sets" ? "items" : tab
    : tab;
  const rows = payload[key];
  if (!Array.isArray(rows)) throw new Error(`Missing catalog resource: ${key}`);
  return rows;
}
