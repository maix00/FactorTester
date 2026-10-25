export type PageScope = "desktop" | "mobile" | "both";

export interface PageDefinition {
  id: string;
  route: string;
  title: string;
  scope: PageScope;
  mobileTab?: string;
}

const pages = new Map<string, PageDefinition>();

export function registerPage(definition: PageDefinition): void {
  if (!definition.id || !definition.route || !definition.title) {
    throw new Error("page id, route and title are required");
  }
  if (pages.has(definition.id)) {
    throw new Error(`duplicate page id: ${definition.id}`);
  }
  pages.set(definition.id, { ...definition });
}

export function getPage(id: string): PageDefinition | undefined {
  return pages.get(id);
}

export function pageForRoute(route: string): PageDefinition | undefined {
  return [...pages.values()].find((page) => page.route === route);
}

export function pagesForScope(scope: "desktop" | "mobile"): PageDefinition[] {
  return [...pages.values()].filter(
    (page) => page.scope === scope || page.scope === "both",
  );
}

export const BUILTIN_PAGES: PageDefinition[] = [
  { id: "research", route: "/research", title: "研究", scope: "both", mobileTab: "research" },
  { id: "jobs", route: "/runs", title: "运行", scope: "both", mobileTab: "runs" },
  { id: "trading", route: "/trading", title: "交易", scope: "both", mobileTab: "trading" },
  { id: "workspace", route: "/workspace", title: "工作区", scope: "mobile", mobileTab: "workspace" },
  { id: "catalog", route: "/catalog", title: "目录", scope: "desktop" },
  { id: "account", route: "/account", title: "账户", scope: "desktop" },
];
