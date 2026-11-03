/** Stable identities embedded in a report are distinct from display labels. */
export type ReportReference = { kind: string; ref: string };

export function reportReference(target: string): ReportReference | null {
  const historical = /^#tr-history-([A-Za-z0-9_-]{43})$/.exec(target);
  if (historical) {
    const raw = atob(historical[1].replaceAll("-","+").replaceAll("_","/") + "=");
    const digest = Array.from(raw, value => value.charCodeAt(0).toString(16).padStart(2,"0")).join("");
    return {kind:"historical_reference",ref:"historical-ref:v1:" + digest};
  }
  let url: URL;
  try { url = new URL(target); } catch { return null; }
  if (url.username || url.password || url.search || url.hash) return null;
  if (url.protocol === "factortester-local:") {
    return /^[a-f0-9]{24}$/i.test(url.hostname) && (!url.pathname || url.pathname === "/")
      ? {kind:"local_resource", ref:url.hostname} : null;
  }
  if (url.protocol !== "factortester:" && url.protocol !== "traderesearch:") return null;
  let ref: string;
  try { ref = decodeURIComponent(url.pathname.replace(/^\//, "")); } catch { return null; }
  const kind = url.hostname.replaceAll("-", "_");
  return /^[a-z][a-z0-9_]*$/.test(kind) && ref ? {kind,ref} : null;
}
