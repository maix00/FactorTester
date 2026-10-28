/** Match the same product fields that the directory shows, without changing server pagination. */
export function catalogSearchMatches(query: string, displayed: string[], extra: unknown[] = []): boolean {
  const needle = query.trim().toLocaleLowerCase();
  return !needle || [...displayed, ...extra].some(value =>
    typeof value === "string" && value.toLocaleLowerCase().includes(needle));
}
