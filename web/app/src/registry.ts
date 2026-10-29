export type PageScope = "desktop" | "mobile" | "both";

export interface PageDefinition {
  id: string;
  route: string;
  title: string;
  scope: PageScope;
  mobileTab?: string;
  icon?: string;
  sidebarVisible?: boolean;
  requiredAdminCapability?: string;
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

export function pagesForAdminCapabilities(
  scope: "desktop" | "mobile",
  capabilities: readonly string[] = [],
): PageDefinition[] {
  return pagesForScope(scope).filter(
    (page) => !page.requiredAdminCapability || capabilities.includes(page.requiredAdminCapability),
  );
}

export const BUILTIN_PAGES: PageDefinition[] = [
  { id: "research", route: "/research?section=researches", title: "研究", scope: "both", mobileTab: "research", icon: "research" },
  { id: "configuration", route: "/backtest?view=configuration", title: "测试", scope: "both", mobileTab: "tests", icon: "settings" },
  { id: "jobs", route: "/jobs?section=types", title: "任务队列", scope: "both", icon: "runs" },
  { id: "trading", route: "/trading", title: "交易台", scope: "both", mobileTab: "trading", icon: "trading" },
  { id: "products", route: "/products", title: "产品库", scope: "both", icon: "catalog" },
  { id: "factors", route: "/factors", title: "因子库", scope: "both", icon: "factor" },
  { id: "strategies", route: "/strategies?scope=public", title: "策略库", scope: "both", icon: "strategy" },
  { id: "admin", route: "/admin", title: "管理员功能", scope: "both", icon: "account", requiredAdminCapability: "admin_console:manage" },
  { id: "more", route: "/app?view=more", title: "更多功能", scope: "mobile", mobileTab: "more", icon: "workspace", sidebarVisible: false },
  { id: "settings", route: "/settings/account", title: "设置", scope: "both", icon: "settings", sidebarVisible: false },
  { id: "source-detail", route: "/products/sources/detail", title: "数据源族", scope: "both", icon: "catalog", sidebarVisible: false },
  { id: "product-detail", route: "/products/product", title: "产品详情", scope: "both", icon: "catalog", sidebarVisible: false },
  { id: "job-detail", route: "/jobs", title: "任务详情", scope: "both", icon: "runs", sidebarVisible: false },
];
