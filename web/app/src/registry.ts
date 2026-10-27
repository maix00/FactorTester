export type PageScope = "desktop" | "mobile" | "both";

export interface PageDefinition {
  id: string;
  route: string;
  title: string;
  scope: PageScope;
  mobileTab?: string;
  icon?: string;
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
  { id: "research", route: "/research?section=researches", title: "研究", scope: "both", mobileTab: "research", icon: "research" },
  { id: "jobs", route: "/jobs?section=types", title: "运行", scope: "both", mobileTab: "runs", icon: "runs" },
  { id: "configuration", route: "/backtest?view=configuration", title: "测试配置", scope: "both", icon: "runs" },
  { id: "trading", route: "/backtest", title: "交易", scope: "both", mobileTab: "trading", icon: "trading" },
  { id: "workspace", route: "/research?section=researches", title: "工作区", scope: "mobile", mobileTab: "workspace", icon: "workspace" },
  { id: "settings", route: "/settings", title: "设置", scope: "mobile", mobileTab: "settings", icon: "account" },
  { id: "catalog", route: "/products", title: "目录", scope: "desktop", icon: "catalog" },
  { id: "account", route: "/settings", title: "账户", scope: "desktop", icon: "account" },
];
