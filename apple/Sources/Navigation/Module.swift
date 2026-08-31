import Foundation

/// 一个首页模块条目 —— 与 Manager `/api/modules` 的 schema 对应。
/// Manager 是权限与顺序的唯一来源；这里仅保留渲染所需的兼容镜像。
struct Module: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let desc: String
    /// web 端 emoji 图标（原生端优先用 sfSymbol，这里作兜底文本）。
    let icon: String
    /// 苹果原生 SF Symbol 名称。
    let sfSymbol: String?
    /// 服务器路由，例如 "/jobs"。
    let path: String
    let requiresAuth: Bool
    /// 非空时仅这些角色可见。
    let roles: [String]
    /// 后端导航树中的子选项卡。
    let children: [Module]
    /// 后端决定模块出现在哪些客户端导航表面；客户端只负责渲染。
    let sidebarVisible: Bool
    let homeVisible: Bool
    let pinned: Bool
    let tabBehavior: String

    init(
        id: String,
        title: String,
        desc: String = "",
        icon: String = "",
        sfSymbol: String? = nil,
        path: String,
        requiresAuth: Bool = true,
        roles: [String] = [],
        children: [Module] = [],
        sidebarVisible: Bool = true,
        homeVisible: Bool = true,
        pinned: Bool = true,
        tabBehavior: String = "standard"
    ) {
        self.id = id
        self.title = title
        self.desc = desc
        self.icon = icon
        self.sfSymbol = sfSymbol
        self.path = path
        self.requiresAuth = requiresAuth
        self.roles = roles
        self.children = children
        self.sidebarVisible = sidebarVisible
        self.homeVisible = homeVisible
        self.pinned = pinned
        self.tabBehavior = tabBehavior
    }

    enum CodingKeys: String, CodingKey {
        case id, title, desc, icon, sfSymbol, path, requiresAuth, roles,
             children, sidebarVisible, homeVisible, pinned
        case tabBehavior = "tab_behavior"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        desc = try c.decodeIfPresent(String.self, forKey: .desc) ?? ""
        icon = try c.decodeIfPresent(String.self, forKey: .icon) ?? ""
        sfSymbol = try c.decodeIfPresent(String.self, forKey: .sfSymbol)
        path = try c.decode(String.self, forKey: .path)
        requiresAuth = try c.decodeIfPresent(Bool.self, forKey: .requiresAuth) ?? true
        roles = try c.decodeIfPresent([String].self, forKey: .roles) ?? []
        children = try c.decodeIfPresent([Module].self, forKey: .children) ?? []
        sidebarVisible = try c.decodeIfPresent(Bool.self, forKey: .sidebarVisible) ?? true
        homeVisible = try c.decodeIfPresent(Bool.self, forKey: .homeVisible) ?? true
        pinned = try c.decodeIfPresent(Bool.self, forKey: .pinned) ?? true
        tabBehavior = try c.decodeIfPresent(String.self, forKey: .tabBehavior) ?? "standard"
    }

    /// 给定当前用户角色，是否对其可见。
    func isVisible(forRole role: String?) -> Bool {
        roles.isEmpty || roles.contains(role ?? "")
    }

    /// Used only when Manager 7998 is temporarily unavailable.  It keeps the
    /// existing client usable without becoming a second permission source.
    static let fallbackModules: [Module] = [
        Module(
            id: "home", title: "主页", path: "/",
            requiresAuth: false, sidebarVisible: true, homeVisible: false
        ),
        Module(
            id: "research", title: "研究",
            desc: "研究报告、研究图与研究身份",
            sfSymbol: "chart.xyaxis.line",
            path: "/research?section=researches", requiresAuth: false,
            children: [
                Module(id: "research.reports", title: "研究报告", path: "/research?section=reports", requiresAuth: false),
                Module(id: "research.evidence", title: "证据", path: "/research?section=evidence"),
                Module(id: "research.graph", title: "研究图", path: "/research?section=graph"),
                Module(id: "research.profiles", title: "研究身份", path: "/research?section=profiles"),
                Module(id: "research.agent-models", title: "智能体模型", path: "/research?section=agent-models"),
            ]
        ),
        Module(
            id: "ic-test", title: "IC 测试", path: "/ic-test",
            sidebarVisible: false, homeVisible: false, tabBehavior: "new"
        ),
        Module(
            id: "backtest", title: "回测", path: "/backtest",
            sidebarVisible: false, homeVisible: false, tabBehavior: "new"
        ),
        Module(
            id: "jobs", title: "测试", desc: "选择测试类型或查看测试任务",
            path: "/jobs?section=types", requiresAuth: false,
            children: [
                Module(
                    id: "jobs.types", title: "测试类型",
                    desc: "选择要运行的测试类型",
                    path: "/jobs?section=types", requiresAuth: false,
                    children: [
                        Module(
                            id: "ic-test", title: "IC 测试",
                            desc: "配置并运行因子 IC 测试",
                            sfSymbol: "chart.xyaxis.line", path: "/ic-test",
                            tabBehavior: "new"
                        ),
                        Module(
                            id: "backtest", title: "回测",
                            desc: "配置并运行分组回测",
                            sfSymbol: "chart.line.uptrend.xyaxis",
                            path: "/backtest", tabBehavior: "new"
                        ),
                    ],
                    sidebarVisible: false, homeVisible: false, pinned: false
                ),
                Module(
                    id: "jobs.list", title: "测试任务",
                    desc: "查看测试任务、进度、结果与生成物",
                    path: "/jobs?section=tasks", requiresAuth: false,
                    sidebarVisible: false, homeVisible: false, pinned: false
                ),
            ]
        ),
        Module(id: "factors", title: "因子库", path: "/factors", requiresAuth: false),
        Module(id: "products", title: "产品库", path: "/products", requiresAuth: false),
        Module(
            id: "manager", title: "服务器管理", sfSymbol: "server.rack",
            path: "/manager",
            roles: ["super_admin"], sidebarVisible: false, pinned: false
        ),
        Module(
            id: "sqlite_web", title: "数据库", sfSymbol: "cylinder.split.1x2",
            path: "/sqlite-web/",
            roles: ["super_admin"], sidebarVisible: false, pinned: false
        ),
        Module(
            id: "docs", title: "技术文档", sfSymbol: "book", path: "/docs",
            requiresAuth: false, sidebarVisible: false, pinned: false,
            tabBehavior: "new"
        ),
    ]
}

struct ModuleManifest: Codable {
    let version: Int?
    let modules: [Module]
}
