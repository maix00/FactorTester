export interface LayoutPage {
  id: string;
  pageId: string;
  groupId: string;
  order: number;
}

export interface LayoutSnapshot {
  version: 1;
  pages: LayoutPage[];
}

export interface LayoutStore {
  save(snapshot: LayoutSnapshot): void;
  load(): LayoutSnapshot | null;
}

export function serializeLayout(snapshot: LayoutSnapshot): string {
  const pages = [...snapshot.pages]
    .sort((a, b) => a.order - b.order)
    .map(({ pageId, groupId, order }) => ({ pageId, groupId, order }));
  return JSON.stringify({ version: 1, pages });
}

export function restoreLayout(raw: string | null): LayoutSnapshot | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<LayoutSnapshot>;
    if (value.version !== 1 || !Array.isArray(value.pages)) return null;
    return {
      version: 1,
      pages: value.pages
        .filter((page) => page && typeof page.pageId === "string" && typeof page.groupId === "string")
        .map((page, index) => ({
          id: `${page.groupId}:${page.pageId}:${index}`,
          pageId: page.pageId,
          groupId: page.groupId,
          order: Number.isFinite(page.order) ? Number(page.order) : index,
        })),
    };
  } catch {
    return null;
  }
}

export function createMemoryLayoutStore(initial: string | null = null): LayoutStore {
  let current = initial;
  return {
    save(snapshot) { current = serializeLayout(snapshot); },
    load() { return restoreLayout(current); },
  };
}

/** Persist workspace references only within the authenticated principal. */
export function workspaceLayoutKey(principal:string):string { return `tr.workspace.layout.v3:${encodeURIComponent(principal)}`; }
