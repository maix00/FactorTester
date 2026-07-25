import Foundation

enum ClientTabContent {
    case home
    case module(Module)
    case adapter(ClientAdapterModel)
    case web(path: String)
    case research
    case workPackage(ResearchDirectoryItem)
    case profiles
    case profile(id: String)
    case accountSettings
    case manager
    case jobs
}

struct ClientTab: Identifiable {
    let id: String
    let title: String
    let systemImage: String
    let content: ClientTabContent

    static let home = ClientTab(
        id: "home",
        title: "主页",
        systemImage: "square.grid.2x2",
        content: .home
    )

    static func module(_ module: Module) -> ClientTab {
        ClientTab(
            id: "module:\(module.id)",
            title: module.title,
            systemImage: module.sfSymbol ?? "square.stack.3d.up",
            content: .module(module)
        )
    }

    static func adapter(_ adapter: ClientAdapterModel) -> ClientTab {
        ClientTab(
            id: "adapter:\(adapter.id)",
            title: adapter.displayName,
            systemImage: "desktopcomputer",
            content: .adapter(adapter)
        )
    }

    static func web(
        id: String,
        title: String,
        systemImage: String,
        path: String
    ) -> ClientTab {
        ClientTab(
            id: "web:\(id)",
            title: title,
            systemImage: systemImage,
            content: .web(path: path)
        )
    }

    static let research = ClientTab(
        id: "research",
        title: "研究",
        systemImage: "chart.xyaxis.line",
        content: .research
    )

    static let jobs = ClientTab(
        id: "jobs",
        title: "测试任务",
        systemImage: "checklist",
        content: .jobs
    )

    static func workPackage(_ item: ResearchDirectoryItem) -> ClientTab {
        ClientTab(
            id: "work-package:\(item.id)",
            title: item.displayTitle,
            systemImage: "point.3.connected.trianglepath.dotted",
            content: .workPackage(item)
        )
    }

    static let profiles = ClientTab(
        id: "profiles",
        title: "Profiles",
        systemImage: "person.2.crop.square.stack",
        content: .profiles
    )

    static func profile(id: String, title: String) -> ClientTab {
        ClientTab(
            id: "profile:\(id)",
            title: title,
            systemImage: "person.crop.rectangle.stack",
            content: .profile(id: id)
        )
    }

    static let accountSettings = ClientTab(
        id: "account-settings",
        title: "用户名/登录",
        systemImage: "person.crop.circle",
        content: .accountSettings
    )

    static let manager = ClientTab(
        id: "manager",
        title: "服务器管理",
        systemImage: "server.rack",
        content: .manager
    )

    static let factorLibrary = ClientTab.web(
        id: "factor-library",
        title: "因子库",
        systemImage: "function",
        path: "/custom-factors/library"
    )

    static let products = ClientTab.web(
        id: "products",
        title: "产品",
        systemImage: "shippingbox",
        path: "/products"
    )

    var isHome: Bool { id == Self.home.id }

    var isPinnedLauncher: Bool {
        [
            "home", "research", "jobs", "web:factor-library", "web:products",
            "profiles", "account-settings",
        ].contains(id)
    }

    var isClosable: Bool { !isPinnedLauncher }
}
