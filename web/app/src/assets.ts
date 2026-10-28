/** Keep unchanged lazy/editor assets on their own content identity. */
export function versionedAssetURL(src: string, versions: Record<string,string>, legacyRevision = ""): string {
  if (!src.startsWith("/research-static/")) return src;
  const url = new URL(src, "https://traderesearch.invalid");
  if (url.searchParams.has("v")) return src;
  const prefix="/research-static/vendor/web-app/";
  const version=url.pathname.startsWith(prefix) ? versions[url.pathname.slice(prefix.length)] : legacyRevision;
  if (!version) return src;
  url.searchParams.set("v",version);
  return url.pathname+url.search+url.hash;
}
export function assetURL(src: string): string {
  const root=document.querySelector<HTMLElement>("[data-tr-web-app]");
  if(!root)return src;
  try { return versionedAssetURL(src,JSON.parse(root.dataset.trAssetVersions || "{}"),root.dataset.trLegacyRevision); }
  catch { return src; }
}

const scripts = new Map<string, Promise<void>>();
/** Deduplicate optional assets across independently mounted workspace tabs. */
export function loadScript(src: string): Promise<void> {
  src=assetURL(src);
  let pending = scripts.get(src);
  if (!pending) {
    pending = new Promise<void>((resolve, reject) => {
      const node = document.createElement("script"); node.src = src;
      node.onload = () => resolve(); node.onerror = () => { node.remove(); reject(new Error(`Unable to load ${src}`)); };
      document.head.append(node);
    }).catch((reason) => { scripts.delete(src); throw reason; });
    scripts.set(src, pending);
  }
  return pending;
}
export function loadStylesheet(href: string): void {
  href=assetURL(href);
  if ([...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')].some((node) => node.getAttribute("href") === href)) return;
  const node = document.createElement("link"); node.rel = "stylesheet"; node.href = href; document.head.append(node);
}
