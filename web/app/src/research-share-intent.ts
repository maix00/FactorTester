const storageKey = "tr.research.share.pending";
const fragmentKey = "research_share";
let pending = "";
const validToken = (value:string):boolean => /^[A-Za-z0-9_-]{16,512}$/.test(value);

/** A fragment is not sent to the server; retain it only in this tab across OIDC redirects. */
export function captureResearchShare(): void {
  const fragment = new URLSearchParams(location.hash.replace(/^#/, ""));
  if (!fragment.has(fragmentKey)) return;
  const token = fragment.get(fragmentKey) || "";
  pending = validToken(token) ? token : "";
  try {
    if (pending) sessionStorage.setItem(storageKey, pending);
    else sessionStorage.removeItem(storageKey);
  } catch { /* The in-memory copy remains available until a full page navigation. */ }
  fragment.delete(fragmentKey);
  const rest = fragment.toString();
  history.replaceState(history.state, "", `${location.pathname}${location.search}${rest ? `#${rest}` : ""}`);
}

export function pendingResearchShare(): string {
  if (pending) return pending;
  try {
    const stored = sessionStorage.getItem(storageKey) || "";
    if (validToken(stored)) return stored;
    sessionStorage.removeItem(storageKey);
    return "";
  } catch { return ""; }
}

export function clearResearchShare(): void {
  pending = "";
  try { sessionStorage.removeItem(storageKey); } catch { /* storage is optional */ }
}
