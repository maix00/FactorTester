import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const resources = {
  zh: {
    common: {
      resetLayout: "重置布局", settings: "设置", close: "关闭", pages: "{{count}} 个页面",
      loading: "正在加载…", loadFailed: "读取失败", empty: "暂无数据", language: "语言",
      filter: "筛选", total: "共 {{count}} 条", collapse: "收起侧栏", expand: "展开侧栏",
      nav: { research: "研究", jobs: "运行", trading: "交易", workspace: "工作区", catalog: "目录", account: "账户" },
      jobs: { task: "任务", status: "状态", jobId: "Job ID", updated: "更新时间", statusFilter: "按状态筛选", recent: "最近运行" },
      workspace: { title: "工作区", desc: "已打开和最近访问的页面" },
    },
  },
  en: {
    common: {
      resetLayout: "Reset layout", settings: "Settings", close: "Close", pages: "{{count}} pages",
      loading: "Loading…", loadFailed: "Load failed", empty: "No data", language: "Language",
      filter: "Filter", total: "{{count}} items", collapse: "Collapse sidebar", expand: "Expand sidebar",
      nav: { research: "Research", jobs: "Runs", trading: "Trading", workspace: "Workspace", catalog: "Catalog", account: "Account" },
      jobs: { task: "Task", status: "Status", jobId: "Job ID", updated: "Updated", statusFilter: "Filter by status", recent: "Recent runs" },
      workspace: { title: "Workspace", desc: "Open and recently visited pages" },
    },
  },
} as const;

export type Language = keyof typeof resources;

export function preferredLanguage(): Language {
  const saved = localStorage.getItem("tr.language");
  if (saved === "zh" || saved === "en") return saved;
  const legacy = localStorage.getItem("ft-language");
  if (legacy === "en") return "en";
  if (legacy === "zh-Hans") return "zh";
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function persistLanguage(language: Language): void {
  localStorage.setItem("tr.language", language);
  localStorage.setItem("ft-language", language === "en" ? "en" : "zh-Hans");
  document.documentElement.lang = language === "en" ? "en" : "zh-Hans";
  void fetch("/api/client/preferences", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language: language === "en" ? "en" : "zh-Hans" }),
  }).catch(() => undefined);
}

i18n.use(initReactI18next).init({
  resources,
  lng: preferredLanguage(),
  fallbackLng: "zh",
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

document.documentElement.lang = i18n.language === "en" ? "en" : "zh-Hans";

export default i18n;
