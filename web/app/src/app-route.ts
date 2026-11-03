/** Keep launch intent in this history entry, never in the visible app URL. */
export function appEntrySearch(): string {
  return location.search || (typeof history !== "undefined" ? history.state?.trEntrySearch : "") || "";
}
export function cleanAppURL(): void {
  if (location.pathname !== "/app") return;
  const search = appEntrySearch();
  const params = new URLSearchParams(search);
  const authError = params.get("auth_error");
  params.delete("auth_error");
  history.replaceState({...history.state, ...(authError ? {trAuthError:authError} : {}), trEntrySearch: params.toString() ? `?${params}` : ""}, "", "/app");
}
