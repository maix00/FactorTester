/** Keep launch intent in this history entry, never in the visible app URL. */
export function appEntrySearch(): string {
  return location.search || history.state?.trEntrySearch || "";
}
export function cleanAppURL(): void {
  if (location.pathname !== "/app") return;
  const search = appEntrySearch();
  const params = new URLSearchParams(search);
  params.delete("auth_error");
  history.replaceState({...history.state, trEntrySearch: params.toString() ? `?${params}` : ""}, "", "/app");
}
