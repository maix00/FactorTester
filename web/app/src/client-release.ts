/** Beta metadata is verified by this Manager, which serves its immutable asset. */
export function clientInstallerHref(release: Record<string, unknown>, base: string): string | undefined {
  const raw = release.dmg_url || release.url;
  if (typeof raw !== "string" || !raw || typeof release.sha256 !== "string") return undefined;
  try {
    const url = new URL(raw, base);
    const match = /^\/api\/client\/releases\/assets\/beta\/([0-9a-f]{64})\.dmg$/.exec(url.pathname);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !match || match[1] !== release.sha256) return undefined;
    // localhost/127.0.0.1 and externally advertised hostnames must not switch
    // the browser away from its selected Manager or its authenticated origin.
    return new URL(url.pathname, new URL(base).origin).href;
  } catch { return undefined; }
}
