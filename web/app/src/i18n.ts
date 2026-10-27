import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const resources = {
  zh: {
    common: {
      panelLayout: { menu: "排列页面", right: "移到右侧区域", below: "移到下方区域", maximize: "最大化区域", restore: "恢复区域" },
      brand: { name: "TradeResearch", first: "Trade", second: "Research" }, mainNavigation: "主导航", resizeSidebar: "调整侧栏宽度", resetLayout: "重置布局", settings: "设置", close: "关闭", pages: "{{count}} 个页面",
      details: "详情", loading: "正在加载…", loadFailed: "读取失败", empty: "暂无数据", language: "语言",
      configuration: {
        testKind:"测试类型", analysisNames: { backtest: "回测", ic: "IC", factor_evaluation: "因子序列", factor_type_analysis: "因子类型" }, scope: { public: "公共", user_custom: "用户" }, edit: "编辑", preview: "预览", run: "运行", submitted: "已提交运行", strategies: "策略", addStrategy: "添加策略", editStrategy: "编辑策略", add: "添加", cancel: "取消", strategyId: "策略名称",
        sections: { data: "数据与时间", execution: "场所与撮合", funds: "费用与保证金", other: "其他设置" }, runSettings: "运行设置", strategy: "策略", removeStrategy: "移除策略", searchStrategies: "搜索策略", search: "搜索设置项",
        templates: { threshold: "因子阈值买卖策略", "cross-sectional-group": "因子横截面分组第 N 组" },
        strategyFields: { signal: "信号因子", product_group_ref: "产品组", entry_threshold: "入场阈值", exit_threshold: "退出阈值", side_mode: "方向", split_count: "分组数", group_index: "第 N 组" },
        values: { long_short: "多空", long_only: "仅做多", short_only: "仅做空" },
        title: "测试", setup: "配置",
        workspace: "选择工作区", create: "新建配置", newTitle: "新的测试配置", fields: "配置项", json: "JSON",
        reload: "重新读取", save: "保存", saved: "配置已保存", savedState: "已保存", unsaved: "未保存",
        loading: "正在读取配置…", loadingEditor: "正在加载 JSON 编辑器…", chooseWorkspace: "选择工作区或新建配置，开始编辑。",
        addFields: "添加配置项", inputs: "测试输入", analysis: "测试类型", allAnalyses: "全部分析",
        remove: "移除配置项", invalidJSON: "JSON 语法无效，原文已保留，请切回 JSON 修正。", fixErrors: "请先修正配置校验错误。",
        validation: "发现 {{count}} 项校验问题", conflict: "远端配置已更新。本地草稿已保留，请复制草稿或重新读取后合并；不会自动覆盖远端。",
        discardTitle: "保留当前修改？", discardHint: "当前草稿尚未保存。继续会放弃当前修改。", discard: "放弃修改并继续", keepEditing: "继续编辑",
      },
      instrumentFields: { field:"字段",value:"值",type:"类型",source:"来源",labels:{price_increment:"价格步长",price_precision:"价格精度",multiplier:"合约乘数",margin_init:"初始保证金率",margin_maint:"维持保证金率",min_quantity:"最小委托数量",max_quantity:"最大委托数量",currency:"结算币种",lot_size:"每手数量",size_increment:"数量步长",size_precision:"数量精度",activation_ns:"启用时间",expiration_ns:"到期时间"} },
      properties: { none:"无",unknown:"未报告",unreported:"未报告字段（{{count}}）" },
    sources: { none:"无", unreported:"未报告字段（{{count}}）", groups:{coverage:"数据覆盖",access:"访问",data:"数据能力",time:"时间与格式",mapping:"字段映射",engine:"引擎与适配器"}, yes:"是",no:"否", serverProvided:"服务器提供", title:"数据源族", notFound:"数据源族不存在", provider:"提供类型", frequencies:"频率", products:"有数据产品", catalogProducts:"目录产品", availability:"可用性", paths:"产品路径", visitor:"访客访问", allowed:"允许", denied:"不可读取", unknown:"未报告", members:"数据源", member:"数据源", dataKind:"数据类型", depth:"市场深度", properties:"查看属性", capabilityUnavailable:"当前服务能力暂不可用", adapterStatus:"适配状态", validated:"已通过适配器校验", notAdapted:"尚未接入", configurableBooks:"引擎可配置 BookType", origins:{snapshot:"来源快照",service:"当前服务",missing:"无能力快照"}, status:{ready:"可用",empty:"暂无数据",not_probed:"尚未探测",unavailable:"不可用",disabled:"已停用",error:"读取失败"}, fields:{mode_available:"数据模式可用",sampling_mode:"采样模式",data_kind:"数据类型",market_depth:"市场深度",delivery_mode:"数据交付",supported_book_types:"支持 BookType",adapter_id:"适配器",instrument_scope:"Instrument 范围",timezone:"时区",bar_time_semantics:"Bar 时间语义",raw_timestamp_unit:"原始时间戳单位",layout:"数据布局",naming_scheme:"命名规则",time_columns:"时间字段映射",data_columns:"行情字段映射",reason:"可用性说明"} },
    factorResults: { title: "因子序列", product: "品种", layers: "因子层级", chart: "行情与因子序列", priceUnavailable: "行情暂不可用" },
    market: { exchange: "交易场所", description: "名称", liveUnavailable: "当前数据源不提供实时数据", title: "行情数据", info: "数据源信息", settings: "图表设置", fullscreen: "全屏", loading: "正在读取行情数据…", loadFailed: "行情数据读取失败", noData: "暂无数据", instrument: "交易标识", terms: "期限结构", identifier: "交易标识", start: "开始日期", end: "结束日期", data: "数据频率", fields: "产品字段", source: "数据源", auto: "自动选择", live: "实时", adjustment: "价格序列", raw: "原始价格", adjusted: "复权价格", frequency: "K 线频率", range: "时间范围", timeZone: "显示时区", productZone: "产品时区", systemZone: "系统时区", saveLoad: "保存并加载", outsideRange: "该区间不在已加载数据内，请扩大时间范围", invalidRange: "请选择有效的开始和结束日期", open: "开盘价", high: "最高价", low: "最低价", close: "收盘价", volume: "成交量", openInterest: "持仓量", time: "时间", closePanel: "关闭", candle: "蜡烛详情", chart: "行情 K 线、成交量和持仓量", roll: "换主力", rollTo: "主力切换至", forward_adjustment_mul: "前复权乘法", forward_adjustment_add: "前复权加法", backward_adjustment_mul: "后复权乘法", backward_adjustment_add: "后复权加法", adjustment_ratio: "换月比值", intervals: { SOURCE: "原始频率", MIN5: "5 分钟", MIN15: "15 分钟", MIN30: "30 分钟", HOUR1: "1 小时", DAY1: "1 交易日", WEEK1: "1 周", LIVE: "实时" }, ranges: { day: "最近一天", month: "最近一个月", year: "最近一年", ytd: "今年以来", all: "全部", custom: "自定义" } },
      library: { visibility: "可见范围", type: "类型", defaultValue: "默认值", description: "说明", identity: "冻结身份", references: { contract: "产品", "continuous-contract": "连续产品", factor: "因子", strategy: "策略" }, formula: "计算公式", search: "搜索名称、家族或所有者", allFamilies: "全部因子家族", allOwners: "全部所有者", reset: "重置", version: "版本", owner: "所有者", frozen: "已冻结", scopes: { strategyFamilies: "策略家族", public: "公共策略", mine: "我的策略", subordinates: "下级用户策略", shared: "共享策略" } },
      strategyDetail: { shares: "共享", principal: "用户标识", share: "共享", revoke: "撤回共享", revokeConfirm: "撤回对此用户的共享？", archive: "归档", archiveConfirm: "确认归档该策略？", reference: "策略引用", sourceHash: "源码哈希", history: "历史版本", created: "创建时间", edit: "编辑策略", revisionMismatch: "版本响应与选择不符", visibility: { private: "仅自己", shared: "指定共享", public: "公开" } },
      pagination: { label: "分页", previous: "上一页", next: "下一页", page: "第 {{page}} 页", pageSize: "每页数量" },
      filter: "筛选", total: "共 {{count}} 条", collapse: "收起侧栏", expand: "展开侧栏", back: "返回",
      pageRenderFailed: "页面渲染失败", retry: "重试", available: "可用",
      catalog: { groups: "产品组", hint: "产品组与产品目录", all: "全部产品", members: "个成员", legacy: "打开完整目录", products: "产品", factors: "因子库", families: "因子家族", sets: "因子集", strategies: "策略库", sources: "数据源", categories: "分类", reference: "引用查询", referenceHint: "输入引用目标" },
      research: { hint: "研究报告与研究工作区", legacy: "打开完整研究页", tabResearches: "研究工作区", tabReports: "研究报告", openEditor: "打开研究编辑器" },
      report: { addParagraph: "添加段落", paragraphTitle: "段落标题", paragraphBody: "段落正文", remove: "删除", removeSelected: "批量删除 {{count}} 项", attachments: "附件", open: "打开", markdown: "Agent Markdown", operationFailed: "报告操作失败" },
      trading: { runtime: "运行状态", engine: "引擎", mode: "模式", connections: "连接状态", connection: "连接", marketData: "实时行情", reconciliation: "账户对账", accounts: "账户与持仓", accountUnreported: "服务端尚未提供经对账的账户数据", readOnly: "仅可查看", unavailable: "不可用", unreported: "未报告", notInstalled: "未安装 NautilusTrader", reasons: { "live data adapter not configured": "未配置实时行情适配器", "venue execution adapter not configured": "未配置券商执行适配器" }, paper: "模拟交易", live: "实盘交易", noBroker: "券商接入尚未开放", capabilities: "引擎能力", hint: "策略家族与回测", open: "打开回测", legacy: "回测工作台", ic: "IC 测试", factorSeries: "因子序列", familyThreshold: "因子阈值策略家族", familyThresholdHint: "按因子阈值生成交易信号的公共规则模板。", familyGroup: "因子分组第N组策略家族", familyGroupHint: "按因子截面分组选择第 N 组的公共规则模板。" },
      unexpectedError: "发生未预期错误", unhandledRejection: "未处理的异步错误",
      nav: { research: "研究", jobs: "任务队列", configuration: "测试", trading: "交易台", more: "更多功能", products: "产品库", factors: "因子库", strategies: "策略库", "job-detail": "任务详情", "source-detail": "数据源族", "product-detail": "产品详情", workspace: "更多功能", settings: "设置", catalog: "目录", account: "账户" },
      editor: { objectRequired: "请输入 JSON 对象", newFactor: "新建因子", newStrategy: "新建策略", newFamily: "新建家族", name: "名称", entrypoint: "入口", source: "源码", requirements: "依赖", parameters: "参数", missingIdentity: "缺少冻结身份" },
      jobs: { noNautilusContract:"此任务没有冻结的 Nautilus 执行契约", scope: "任务范围", scopes: { server: "服务器任务", "cross-server": "跨服务器任务", mine: "本账号任务", subordinates: "下级用户任务" }, subordinate: "选择下级用户", loginRequired: "请先登录", server: "服务器", port: "业务端口", states: { queued: "排队中", running: "运行中", paused: "已暂停", succeeded: "已完成", failed: "失败", cancelled: "已取消" }, overview: "概览", results: "结果", waitingResults: "等待结果", output: "生成物", task: "任务", status: "状态", jobId: "Job ID", updated: "更新时间", detail: "运行详情", configuration: "运行配置", inputs: "输入与附件", cancel: "取消运行", cancelled: "已请求取消", download: "下载", downloadUnavailable: "没有可用的下载地址", statusFilter: "按状态筛选", recent: "最近运行" },
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
      panelLayout: { menu: "Arrange page", right: "Move to right region", below: "Move to lower region", maximize: "Maximize region", restore: "Restore regions" },
      brand: { name: "TradeResearch", first: "Trade", second: "Research" }, mainNavigation: "Main navigation", resizeSidebar: "Resize sidebar", resetLayout: "Reset layout", settings: "Settings", close: "Close", pages: "{{count}} pages",
      details: "Details", loading: "Loading…", loadFailed: "Load failed", empty: "No data", language: "Language",
      configuration: {
        testKind:"Test type", analysisNames: { backtest: "Backtest", ic: "IC", factor_evaluation: "Factor series", factor_type_analysis: "Factor type" }, scope: { public: "Public", user_custom: "User" }, edit: "Edit", preview: "Preview", run: "Run", submitted: "Run submitted", strategies: "Strategies", addStrategy: "Add strategy", editStrategy: "Edit strategy", add: "Add", cancel: "Cancel", strategyId: "Strategy name",
        groups: {"group_strategy": "Grouping", "position_policy": "Position policy", "rebalance_trigger": "Rebalancing", "target_allocation": "Target allocation", "term_carry_strategy": "Term carry", "engine": "Engine", "time": "Time range", "capital": "Capital", "order": "Order execution", "accounting": "Accounting", "delivery_force_close": "Delivery closeout", "rollover": "Rollover", "data_source": "Data source", "frequency": "Data frequency", "factor": "Factor execution", "calendar": "Backtest clock", "cost": "Fees", "volume_capacity": "Volume participation", "margin": "Margin", "strategy_book": "Strategy book", "return_frequency": "Forward returns", "delay": "Delay", "ic_method": "IC method", "summary": "Summary", "quantile_portfolio_statistics": "Group portfolio", "price_type": "Price type", "method": "Analysis method"} ,
        sections: { data: "Data and time", execution: "Venues and matching", funds: "Fees and margin", other: "Other settings" }, runSettings: "Run settings", strategy: "Strategy", removeStrategy: "Remove strategy", searchStrategies: "Search strategies", search: "Search settings",
        templates: { threshold: "Factor threshold strategy", "cross-sectional-group": "Factor cross-sectional group N" },
        strategyFields: { signal: "Signal factor", product_group_ref: "Product group", entry_threshold: "Entry threshold", exit_threshold: "Exit threshold", side_mode: "Direction", split_count: "Groups", group_index: "Group index" },
        values: { long_short: "Long and short", long_only: "Long only", short_only: "Short only" },
        title: "Test", setup: "Configuration",
        workspace: "Select workspace", create: "New configuration", newTitle: "New test configuration", fields: "Fields", json: "JSON",
        reload: "Reload", save: "Save", saved: "Configuration saved", savedState: "Saved", unsaved: "Unsaved",
        loading: "Loading configuration…", loadingEditor: "Loading JSON editor…", chooseWorkspace: "Select a workspace or create a configuration to begin.",
        addFields: "Add configuration", inputs: "Test inputs", analysis: "Test type", allAnalyses: "All analyses",
        remove: "Remove field", invalidJSON: "Invalid JSON. Your text is preserved; return to JSON to correct it.", fixErrors: "Correct the configuration errors first.",
        validation: "{{count}} validation issues", conflict: "The remote configuration changed. Your draft is preserved. Copy it or reload and merge; the remote version will not be overwritten.",
        discardTitle: "Keep current changes?", discardHint: "Your draft is not saved. Continuing will discard these changes.", discard: "Discard and continue", keepEditing: "Keep editing",
      },
      instrumentFields: { field:"Field",value:"Value",type:"Type",source:"Source",labels:{price_increment:"Price increment",price_precision:"Price precision",multiplier:"Contract multiplier",margin_init:"Initial margin rate",margin_maint:"Maintenance margin rate",min_quantity:"Minimum order quantity",max_quantity:"Maximum order quantity",currency:"Settlement currency",lot_size:"Lot size",size_increment:"Size increment",size_precision:"Size precision",activation_ns:"Activation time",expiration_ns:"Expiration time"} },
      properties: { none:"None",unknown:"Not reported",unreported:"Unreported fields ({{count}})" },
    sources: { none:"None", unreported:"Unreported fields ({{count}})", groups:{coverage:"Coverage",access:"Access",data:"Data capabilities",time:"Time & format",mapping:"Field mapping",engine:"Engine & adapter"}, yes:"Yes",no:"No", serverProvided:"Server-provided", title:"Data source family", notFound:"Data source family not found", provider:"Provider type", frequencies:"Frequencies", products:"Products with data", catalogProducts:"Catalog products", availability:"Availability", paths:"Product paths", visitor:"Visitor access", allowed:"Allowed", denied:"Not readable", unknown:"Not reported", members:"Data sources", member:"Data source", dataKind:"Data kind", depth:"Market depth", properties:"View properties", capabilityUnavailable:"Current service capabilities unavailable", adapterStatus:"Adapter status", validated:"Adapter validated", notAdapted:"Not adapted", configurableBooks:"Engine-configurable BookType", origins:{snapshot:"Source snapshot",service:"Current service",missing:"No capability snapshot"}, status:{ready:"Ready",empty:"No data",not_probed:"Not probed",unavailable:"Unavailable",disabled:"Disabled",error:"Read failed"}, fields:{mode_available:"Data mode available",sampling_mode:"Sampling mode",data_kind:"Data kind",market_depth:"Market depth",delivery_mode:"Delivery mode",supported_book_types:"BookType support",adapter_id:"Adapter",instrument_scope:"Instrument scope",timezone:"Time zone",bar_time_semantics:"Bar time semantics",raw_timestamp_unit:"Raw timestamp unit",layout:"Data layout",naming_scheme:"Naming scheme",time_columns:"Time column mapping",data_columns:"Market column mapping",reason:"Availability reason"} },
    factorResults: { title: "Factor series", product: "Product", layers: "Factor layers", chart: "Market data and factor series", priceUnavailable: "Market data unavailable" },
    market: { exchange: "Venue", description: "Description", liveUnavailable: "This source does not provide live data", title: "Market data", info: "Data source information", settings: "Chart settings", fullscreen: "Fullscreen", loading: "Loading market data…", loadFailed: "Market data load failed", noData: "No data", instrument: "Instrument", terms: "Term structure", identifier: "Instrument", start: "Start date", end: "End date", data: "Frequencies", fields: "Product fields", source: "Data source", auto: "Automatic", live: "Live", adjustment: "Price series", raw: "Raw prices", adjusted: "Adjusted prices", frequency: "Candle frequency", range: "Time range", timeZone: "Display time zone", productZone: "Product time zone", systemZone: "System time zone", saveLoad: "Save and load", outsideRange: "This interval is outside the loaded data; expand the time range", invalidRange: "Choose valid start and end dates", open: "Open", high: "High", low: "Low", close: "Close", volume: "Volume", openInterest: "Open interest", time: "Time", closePanel: "Close", candle: "Candle details", chart: "Price candles, volume and open interest", roll: "Roll", rollTo: "Switch to", forward_adjustment_mul: "Forward multiplier", forward_adjustment_add: "Forward addition", backward_adjustment_mul: "Backward multiplier", backward_adjustment_add: "Backward addition", adjustment_ratio: "Roll ratio", intervals: { SOURCE: "Source frequency", MIN5: "5 minutes", MIN15: "15 minutes", MIN30: "30 minutes", HOUR1: "1 hour", DAY1: "1 trading day", WEEK1: "1 week", LIVE: "Live" }, ranges: { day: "Last available day", month: "Last available month", year: "Last available year", ytd: "Year to date", all: "All", custom: "Custom" } },
      library: { visibility: "Visibility", type: "Type", defaultValue: "Default", description: "Description", identity: "Frozen identity", references: { contract: "Instrument", "continuous-contract": "Continuous product", factor: "Factor", strategy: "Strategy" }, formula: "Formula", search: "Search name, family or owner", allFamilies: "All factor families", allOwners: "All owners", reset: "Reset", version: "Version", owner: "Owner", frozen: "Frozen", scopes: { strategyFamilies: "Strategy families", public: "Public strategies", mine: "My strategies", subordinates: "Subordinate strategies", shared: "Shared strategies" } },
      strategyDetail: { shares: "Sharing", principal: "Principal", share: "Share", revoke: "Revoke", revokeConfirm: "Revoke sharing for this principal?", archive: "Archive", archiveConfirm: "Archive this strategy?", reference: "Strategy reference", sourceHash: "Source hash", history: "Revision history", created: "Created", edit: "Edit strategy", revisionMismatch: "Revision response does not match selection", visibility: { private: "Private", shared: "Shared", public: "Public" } },
      pagination: { label: "Pagination", previous: "Previous", next: "Next", page: "Page {{page}}", pageSize: "Page size" },
      filter: "Filter", total: "{{count}} items", collapse: "Collapse sidebar", expand: "Expand sidebar", back: "Back",
      pageRenderFailed: "Page render failed", retry: "Retry", available: "Available",
      catalog: { groups: "Product groups", hint: "Product groups and products", all: "All products", members: "members", legacy: "Open full catalog", products: "Products", factors: "Factor library", families: "Families", sets: "Factor sets", strategies: "Strategy library", sources: "Sources", categories: "Categories", reference: "Reference lookup", referenceHint: "Enter a reference target" },
      research: { hint: "Research reports and workspaces", legacy: "Open full research page", tabResearches: "Workspaces", tabReports: "Reports", openEditor: "Open research editor" },
      report: { addParagraph: "Add paragraph", paragraphTitle: "Paragraph title", paragraphBody: "Paragraph body", remove: "Remove", removeSelected: "Remove {{count}} selected", attachments: "Attachments", open: "Open", markdown: "Agent Markdown", operationFailed: "Report operation failed" },
      trading: { runtime: "Runtime", engine: "Engine", mode: "Mode", connections: "Connections", connection: "Connection", marketData: "Live market data", reconciliation: "Account reconciliation", accounts: "Accounts and positions", accountUnreported: "Reconciled account data has not been reported", readOnly: "Read only", unavailable: "Unavailable", unreported: "Not reported", notInstalled: "NautilusTrader is not installed", reasons: { "live data adapter not configured": "Live data adapter not configured", "venue execution adapter not configured": "Venue execution adapter not configured" }, paper: "Paper trading", live: "Live trading", noBroker: "Broker connection is not available", capabilities: "Engine capabilities", hint: "Strategy families and backtests", open: "Open backtest", legacy: "Backtest workbench", ic: "IC test", factorSeries: "Factor series", familyThreshold: "Factor threshold strategy family", familyThresholdHint: "Public rule template that trades factor threshold signals.", familyGroup: "Factor group N strategy family", familyGroupHint: "Public rule template that trades the Nth cross-sectional factor group." },
      unexpectedError: "Unexpected error", unhandledRejection: "Unhandled promise rejection",
      nav: { research: "Research", jobs: "Job queue", configuration: "Test", trading: "Trading", more: "More", products: "Products", factors: "Factors", strategies: "Strategies", "job-detail": "Job detail", "source-detail": "Data source family", "product-detail": "Product detail", workspace: "More", settings: "Settings", catalog: "Catalog", account: "Account" },
      editor: { objectRequired: "Enter a JSON object", newFactor: "New factor", newStrategy: "New strategy", newFamily: "New family", name: "Name", entrypoint: "Entrypoint", source: "Source", requirements: "Requirements", parameters: "Parameters", missingIdentity: "Missing frozen identity" },
      jobs: { noNautilusContract:"This task has no frozen Nautilus execution contract", scope: "Task scope", scopes: { server: "Server", "cross-server": "Cross-server", mine: "My account", subordinates: "Subordinates" }, subordinate: "Select subordinate", loginRequired: "Sign in required", server: "Server", port: "Service port", states: { queued: "Queued", running: "Running", paused: "Paused", succeeded: "Completed", failed: "Failed", cancelled: "Cancelled" }, overview: "Overview", results: "Results", waitingResults: "Awaiting results", output: "Outputs", task: "Task", status: "Status", jobId: "Job ID", updated: "Updated", detail: "Run detail", configuration: "Run configuration", inputs: "Inputs and artifacts", cancel: "Cancel run", cancelled: "Cancellation requested", download: "Download", downloadUnavailable: "No download URL", statusFilter: "Filter by status", recent: "Recent runs" },
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
