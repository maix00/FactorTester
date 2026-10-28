const scripts = new Map<string, Promise<void>>();
/** Deduplicate optional assets across independently mounted workspace tabs. */
export function loadScript(src: string): Promise<void> {
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
  if ([...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')].some((node) => node.getAttribute("href") === href)) return;
  const node = document.createElement("link"); node.rel = "stylesheet"; node.href = href; document.head.append(node);
}
