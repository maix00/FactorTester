import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const resources = {
  zh: {
    common: {
      resetLayout: "重置布局", settings: "设置", close: "关闭", pages: "{{count}} 个页面",
      loading: "正在加载…", loadFailed: "读取失败", empty: "暂无数据", language: "语言",
      configuration: {
        title: "测试配置", hint: "配置项与 JSON 编辑同一份草稿；保存后由服务端校验并冻结运行配置。",
        workspace: "选择工作区", create: "新建配置", newTitle: "新的测试配置", fields: "配置项", json: "JSON",
        reload: "重新读取", save: "保存", saved: "配置已保存", savedState: "已保存", unsaved: "未保存",
        loading: "正在读取配置…", loadingEditor: "正在加载 JSON 编辑器…", chooseWorkspace: "选择工作区或新建配置，开始编辑。",
        addFields: "添加配置项", search: "搜索参数名称或说明", analysis: "分析类型", allAnalyses: "全部分析",
        selectField: "从左侧添加配置项，或选择已有配置项编辑。完整文档也可在 JSON 视图修改。",
        remove: "移除配置项", invalidJSON: "JSON 语法无效，原文已保留，请切回 JSON 修正。", fixErrors: "请先修正配置校验错误。",
        validation: "发现 {{count}} 项校验问题", conflict: "远端配置已更新。本地草稿已保留，请复制草稿或重新读取后合并；不会自动覆盖远端。",
        discardTitle: "保留当前修改？", discardHint: "当前草稿尚未保存。继续会放弃当前修改。", discard: "放弃修改并继续", keepEditing: "继续编辑",
        section: { shared: "共享输入", analyses: "分析配置", ui: "显示偏好" },
      },
      filter: "筛选", total: "共 {{count}} 条", collapse: "收起侧栏", expand: "展开侧栏", back: "返回",
      pageRenderFailed: "页面渲染失败", retry: "重试", available: "可用",
      catalog: { hint: "产品组与产品目录", all: "全部产品", members: "个成员", legacy: "打开完整目录", products: "产品", factors: "因子库", families: "因子家族", sets: "因子集", strategies: "策略库", sources: "数据源", categories: "分类", reference: "引用查询", referenceHint: "输入引用目标" },
      research: { hint: "研究报告与研究工作区", legacy: "打开完整研究页", tabResearches: "研究工作区", tabReports: "研究报告", openEditor: "打开研究编辑器" },
      report: { addParagraph: "添加段落", paragraphTitle: "段落标题", paragraphBody: "段落正文", remove: "删除", removeSelected: "批量删除 {{count}} 项", attachments: "附件", open: "打开", markdown: "Agent Markdown", operationFailed: "报告操作失败" },
      trading: { hint: "策略家族与回测", open: "打开回测", legacy: "回测工作台", ic: "IC 测试", factorSeries: "因子序列", familyThreshold: "因子阈值策略家族", familyThresholdHint: "按因子阈值生成交易信号的公共规则模板。", familyGroup: "因子分组第N组策略家族", familyGroupHint: "按因子截面分组选择第 N 组的公共规则模板。" },
      unexpectedError: "发生未预期错误", unhandledRejection: "未处理的异步错误",
      nav: { research: "研究", jobs: "运行", configuration: "测试配置", trading: "交易", workspace: "工作区", settings: "设置", catalog: "目录", account: "账户" },
      jobs: { task: "任务", status: "状态", jobId: "Job ID", updated: "更新时间", detail: "运行详情", configuration: "运行配置", inputs: "输入与附件", cancel: "取消运行", cancelled: "已请求取消", download: "下载", downloadUnavailable: "没有可用的下载地址", statusFilter: "按状态筛选", recent: "最近运行" },
      workspace: { title: "工作区", desc: "已打开和最近访问的页面" },
      notifications: { title: "通知", close: "关闭", empty: "暂无通知", new: "新", bell: "通知中心" },
      more: "加载更多",
      settingsPanel: {
        title: "设置", language: "语言", languageHint: "界面语言与数字/日期格式，时区独立。",
        layout: "工作区布局", layoutHint: "重置 Dockview 标签、分组和分栏。",
        accountSession: "登录账户", accountHint: "当前用于访问研究、任务与工作区的账户", managedByServer: "由服务器会话管理", notSignedIn: "未登录", role: "用户角色", roleHint: "由服务器分配，客户端不能修改",
        migrating: "该设置页仍在旧页面迁移中，完成对应路由后在此启用。", mobileHint: "选择要修改的设置项",
        sections: { account: "账户", server: "服务器", federation: "服务器互联", controlDatabase: "控制数据库", devices: "我的设备", quota: "存储配额", workspace: "工作区", language: "语言", updates: "客户端更新", manager: "管理", docs: "文档", profiles: "研究身份", mihomo: "Mihomo" },
        descriptions: { account: "登录、身份与账户安全", server: "服务器连接与运行状态", federation: "服务器之间的互联与复制", controlDatabase: "控制数据库结构与备份", devices: "设备授权与会话", quota: "存储使用与配额", workspace: "工作区布局与页面", language: "界面语言与格式", updates: "客户端版本与更新", manager: "管理工作树与服务", docs: "技术文档", profiles: "研究身份", mihomo: "Mihomo 网络" },
      },
    },
  },
  en: {
    common: {
      resetLayout: "Reset layout", settings: "Settings", close: "Close", pages: "{{count}} pages",
      loading: "Loading…", loadFailed: "Load failed", empty: "No data", language: "Language",
      configuration: {
        title: "Test configuration", hint: "Fields and JSON edit one draft. The server validates and freezes the run configuration after saving.",
        workspace: "Select workspace", create: "New configuration", newTitle: "New test configuration", fields: "Fields", json: "JSON",
        reload: "Reload", save: "Save", saved: "Configuration saved", savedState: "Saved", unsaved: "Unsaved",
        loading: "Loading configuration…", loadingEditor: "Loading JSON editor…", chooseWorkspace: "Select a workspace or create a configuration to begin.",
        addFields: "Add configuration", search: "Search names or descriptions", analysis: "Analysis type", allAnalyses: "All analyses",
        selectField: "Add a field from the left or select an existing field. Use JSON view to edit the complete document.",
        remove: "Remove field", invalidJSON: "Invalid JSON. Your text is preserved; return to JSON to correct it.", fixErrors: "Correct the configuration errors first.",
        validation: "{{count}} validation issues", conflict: "The remote configuration changed. Your draft is preserved. Copy it or reload and merge; the remote version will not be overwritten.",
        discardTitle: "Keep current changes?", discardHint: "Your draft is not saved. Continuing will discard these changes.", discard: "Discard and continue", keepEditing: "Keep editing",
        section: { shared: "Shared inputs", analyses: "Analyses", ui: "Display preferences" },
      },
      filter: "Filter", total: "{{count}} items", collapse: "Collapse sidebar", expand: "Expand sidebar", back: "Back",
      pageRenderFailed: "Page render failed", retry: "Retry", available: "Available",
      catalog: { hint: "Product groups and products", all: "All products", members: "members", legacy: "Open full catalog", products: "Products", factors: "Factor library", families: "Families", sets: "Factor sets", strategies: "Strategy library", sources: "Sources", categories: "Categories", reference: "Reference lookup", referenceHint: "Enter a reference target" },
      research: { hint: "Research reports and workspaces", legacy: "Open full research page", tabResearches: "Workspaces", tabReports: "Reports", openEditor: "Open research editor" },
      report: { addParagraph: "Add paragraph", paragraphTitle: "Paragraph title", paragraphBody: "Paragraph body", remove: "Remove", removeSelected: "Remove {{count}} selected", attachments: "Attachments", open: "Open", markdown: "Agent Markdown", operationFailed: "Report operation failed" },
      trading: { hint: "Strategy families and backtests", open: "Open backtest", legacy: "Backtest workbench", ic: "IC test", factorSeries: "Factor series", familyThreshold: "Factor threshold strategy family", familyThresholdHint: "Public rule template that trades factor threshold signals.", familyGroup: "Factor group N strategy family", familyGroupHint: "Public rule template that trades the Nth cross-sectional factor group." },
      unexpectedError: "Unexpected error", unhandledRejection: "Unhandled promise rejection",
      nav: { research: "Research", jobs: "Runs", configuration: "Test configuration", trading: "Trading", workspace: "Workspace", settings: "Settings", catalog: "Catalog", account: "Account" },
      jobs: { task: "Task", status: "Status", jobId: "Job ID", updated: "Updated", detail: "Run detail", configuration: "Run configuration", inputs: "Inputs and artifacts", cancel: "Cancel run", cancelled: "Cancellation requested", download: "Download", downloadUnavailable: "No download URL", statusFilter: "Filter by status", recent: "Recent runs" },
      workspace: { title: "Workspace", desc: "Open and recently visited pages" },
      notifications: { title: "Notifications", close: "Close", empty: "No notifications", new: "new", bell: "Notification center" },
      more: "Load more",
      settingsPanel: {
        title: "Settings", language: "Language", languageHint: "Interface language and number/date formats; time zone is separate.",
        layout: "Workspace layout", layoutHint: "Reset Dockview tabs, groups and splits.",
        accountSession: "Signed-in account", accountHint: "Account used to access research, runs and workspaces", managedByServer: "Managed by the server session", notSignedIn: "Not signed in", role: "Role", roleHint: "Assigned by the server; the client cannot change it",
        migrating: "This settings page is still migrating from the legacy route.", mobileHint: "Choose a setting to edit",
        sections: { account: "Account", server: "Server", federation: "Federation", controlDatabase: "Control database", devices: "Devices", quota: "Storage quota", workspace: "Workspace", language: "Language", updates: "Client updates", manager: "Manager", docs: "Docs", profiles: "Profiles", mihomo: "Mihomo" },
        descriptions: { account: "Login, identity and account security", server: "Server connection and runtime", federation: "Server federation and replication", controlDatabase: "Control database schema and backups", devices: "Device authorization and sessions", quota: "Storage usage and limits", workspace: "Workspace layout and pages", language: "Interface language and formats", updates: "Client version and updates", manager: "Worktrees and services", docs: "Technical documentation", profiles: "Research profiles", mihomo: "Mihomo network" },
      },
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
// no-op placeholder
